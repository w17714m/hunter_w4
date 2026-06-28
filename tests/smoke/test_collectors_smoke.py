from __future__ import annotations

import asyncio

import pytest

from src.collectors.computrabajo import ComputrabajoCollector
from src.collectors.elempleo import ElempleoCollector
from src.collectors.linkedin import DEFAULT_PROFILE_DIR, LinkedInCollector


# ---------------------------------------------------------------------------
# Elempleo
# ---------------------------------------------------------------------------

def test_elempleo_smoke() -> None:
    """Una búsqueda real en elempleo — verifica que llega al menos una oferta con Markdown."""
    collector = ElempleoCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'desarrollador backend', 'modalidad': 'remoto'}]

    results = asyncio.run(collector.collect(busqueda))

    _assert_at_least_one_ok(results, fuente='elempleo')


# ---------------------------------------------------------------------------
# Computrabajo
# ---------------------------------------------------------------------------

def test_computrabajo_smoke() -> None:
    """Una búsqueda real en Computrabajo — verifica que llega al menos una oferta con Markdown."""
    collector = ComputrabajoCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'desarrollador backend', 'lugar_trabajo': 'remoto'}]

    results = asyncio.run(collector.collect(busqueda))

    _assert_at_least_one_ok(results, fuente='computrabajo')


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

def test_linkedin_smoke() -> None:
    """Una búsqueda real en LinkedIn — verifica que llega al menos una oferta con Markdown.

    Requiere sesión persistente en data/playwright/linkedin-profile/.
    Si el perfil no existe el test se saltea con instrucciones.
    Si LinkedIn bloquea (HTTP 999 / authwall) el test se saltea — no es un fallo del collector.
    """
    if not DEFAULT_PROFILE_DIR.exists():
        pytest.skip(
            f'Sesión de LinkedIn no encontrada en {DEFAULT_PROFILE_DIR}. '
            'Ejecuta primero: uv run python scripts/login_linkedin_persistent.py'
        )

    collector = LinkedInCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'backend developer', 'geo_id': '100876405', 'orden': 'reciente'}]

    results = asyncio.run(collector.collect(busqueda))

    blocked_statuses = {'blocked', 'login_required', 'captcha'}
    if all(r.get('extraction_status') in blocked_statuses for r in results):
        pytest.skip(
            'LinkedIn bloqueó todas las solicitudes. '
            'Renueva la sesión con: uv run python scripts/login_linkedin_persistent.py'
        )

    _assert_at_least_one_ok(results, fuente='linkedin')


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_at_least_one_ok(results: list[dict], fuente: str) -> None:
    assert results, f'[{fuente}] El collector no devolvió ningún resultado.'

    ok = [r for r in results if r.get('extraction_status') == 'ok']
    estados = [r.get('extraction_status') for r in results]

    assert ok, (
        f'[{fuente}] Ninguna oferta con extraction_status=ok. '
        f'Estados recibidos: {estados}'
    )

    oferta = ok[0]
    assert oferta.get('descripcion_md'), f'[{fuente}] descripcion_md está vacío en la primera oferta ok.'
    assert '<' not in oferta['descripcion_md'], f'[{fuente}] descripcion_md contiene etiquetas HTML crudas.'
    assert oferta.get('url'), f'[{fuente}] url está vacío.'
    assert oferta.get('fuente') == fuente, f'[{fuente}] campo fuente incorrecto: {oferta.get("fuente")}'
    assert 'posted_date' in oferta, f'[{fuente}] falta el campo posted_date.'
