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
    """A real elempleo search — verifies at least one offer with Markdown is returned."""
    collector = ElempleoCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'desarrollador backend', 'modalidad': 'remoto'}]

    results = asyncio.run(collector.collect(busqueda))

    _assert_at_least_one_ok(results, fuente='elempleo')


# ---------------------------------------------------------------------------
# Computrabajo
# ---------------------------------------------------------------------------

def test_computrabajo_smoke() -> None:
    """A real Computrabajo search — verifies at least one offer with Markdown is returned."""
    collector = ComputrabajoCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'desarrollador backend', 'lugar_trabajo': 'remoto'}]

    results = asyncio.run(collector.collect(busqueda))

    _assert_at_least_one_ok(results, fuente='computrabajo')


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

def test_linkedin_smoke() -> None:
    """A real LinkedIn search — verifies at least one offer with Markdown is returned.

    Requires a persistent session in data/playwright/linkedin-profile/.
    If the profile does not exist the test is skipped with instructions.
    If LinkedIn blocks (HTTP 999 / authwall) the test is skipped — not a collector failure.
    """
    if not DEFAULT_PROFILE_DIR.exists():
        pytest.skip(
            f'LinkedIn session not found at {DEFAULT_PROFILE_DIR}. '
            'Run first: uv run python scripts/login_linkedin_persistent.py'
        )

    collector = LinkedInCollector(max_offers_per_search=1)
    busqueda = [{'cargo': 'backend developer', 'geo_id': '100876405', 'orden': 'reciente'}]

    results = asyncio.run(collector.collect(busqueda))

    blocked_statuses = {'blocked', 'login_required', 'captcha'}
    if all(r.get('extraction_status') in blocked_statuses for r in results):
        pytest.skip(
            'LinkedIn blocked all requests. '
            'Renew the session with: uv run python scripts/login_linkedin_persistent.py'
        )

    _assert_at_least_one_ok(results, fuente='linkedin')


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_at_least_one_ok(results: list[dict], fuente: str) -> None:
    assert results, f'[{fuente}] Collector returned no results.'

    ok = [r for r in results if r.get('extraction_status') == 'ok']
    estados = [r.get('extraction_status') for r in results]

    assert ok, (
        f'[{fuente}] No offer with extraction_status=ok. '
        f'Statuses received: {estados}'
    )

    oferta = ok[0]
    assert oferta.get('descripcion_md'), f'[{fuente}] descripcion_md is empty on the first ok offer.'
    assert '<' not in oferta['descripcion_md'], f'[{fuente}] descripcion_md contains raw HTML tags.'
    assert oferta.get('url'), f'[{fuente}] url is empty.'
    assert oferta.get('fuente') == fuente, f'[{fuente}] fuente field incorrect: {oferta.get("fuente")}'
    assert 'posted_date' in oferta, f'[{fuente}] missing posted_date field.'
