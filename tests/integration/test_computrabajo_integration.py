"""Integration test — consulta real a co.computrabajo.com.

Ejecutar manualmente:
    uv run pytest tests/integration/test_computrabajo_integration.py -v -s

Requiere conexión a internet y Playwright instalado.
"""
import asyncio

import pytest

from src.collectors.computrabajo import ComputrabajoCollector


@pytest.mark.integration
def test_computrabajo_live_at_least_one_ok_offer() -> None:
  """Verifica que el collector extrae al menos una oferta con descripcion_md."""
  collector = ComputrabajoCollector(max_offers_per_search=3)
  busquedas = [
    {
      'cargo': 'python developer',
      'lugar_trabajo': 'remoto',
      'fecha_publicacion': 'semana',
    }
  ]

  results = asyncio.run(collector.collect(busquedas))

  assert results, 'No se obtuvo ningún resultado'

  ok_results = [r for r in results if r.get('extraction_status') == 'ok']
  assert ok_results, (
    f'Ningún resultado con extraction_status=ok. '
    f'Estados obtenidos: {[r.get("extraction_status") for r in results]}'
  )

  offer = ok_results[0]
  assert offer['descripcion_md'], 'descripcion_md está vacío'
  assert '<' not in offer['descripcion_md'], 'descripcion_md contiene etiquetas HTML'
  assert offer['fuente'] == 'computrabajo'
  assert offer['url'].startswith('https://co.computrabajo.com/ofertas-de-trabajo/')
