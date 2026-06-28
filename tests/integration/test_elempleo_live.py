import os

import pytest

from src.collectors.elempleo import ElempleoCollector

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_elempleo_live_returns_markdown_results() -> None:
  collector = ElempleoCollector(max_offers_per_search=2)
  offers = await collector.collect([{'cargo': 'desarrollador python', 'ciudad': 'bogota'}])

  valid_offers = [item for item in offers if item.get('extraction_status') == 'ok']
  assert valid_offers, 'No se obtuvo ninguna oferta valida desde elempleo.'
  assert valid_offers[0].get('descripcion_md')
  assert '<div' not in valid_offers[0]['descripcion_md'].lower()

