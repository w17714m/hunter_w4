import re
from urllib.parse import urljoin

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from playwright_stealth import Stealth

from src.collectors.elempleo import ElempleoParser

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
# @pytest.mark.skipif(
#   os.getenv('RUN_INTEGRATION') != '1',
#   reason='Define RUN_INTEGRATION=1 para ejecutar pruebas reales de elempleo con Playwright.',
# )
async def test_elempleo_direct_playwright_search_to_offer_markdown() -> None:
  search_url = 'https://www.elempleo.com/co/ofertas-empleo/trabajo-desarrollador-backend-modalidad-remoto?Salaries=4-45-millones:45-55-millones:55-6-millones:6-8-millones:8-10-millones:10-125-millones:125-15-millones:mas-21-millones:salario-confidencial'
  base_url = 'https://www.elempleo.com'

  try:
    async with async_playwright() as playwright:
      # browser = await playwright.chromium.launch(headless=True)
      browser = await playwright.chromium.launch(headless=False)
      context = await browser.new_context()
      page = await context.new_page()
      page.set_default_timeout(60_000)

      await Stealth().apply_stealth_async(page)

      search_response = await page.goto(search_url, wait_until='domcontentloaded')
      if search_response is None:
        pytest.skip('No hubo respuesta HTTP en la búsqueda de elempleo.')
      if search_response.status >= 400:
        pytest.skip(f'Elempleo respondió HTTP {search_response.status} en búsqueda.')

      search_html = await page.content()
      raw_links = re.findall(r'href=[\'"]([^\'"]+/ofertas-trabajo/[^\'"]+)[\'"]', search_html, flags=re.IGNORECASE)
      unique_links = []
      seen = set()
      for link in raw_links:
        full = urljoin(base_url, link)
        if full in seen:
          continue
        seen.add(full)
        unique_links.append(full)

      assert unique_links, 'No se encontraron links de ofertas reales en la página de búsqueda.'

      offer_response = await page.goto(unique_links[0], wait_until='domcontentloaded')
      if offer_response is None:
        pytest.skip('No hubo respuesta HTTP en la oferta de elempleo.')
      if offer_response.status >= 400:
        pytest.skip(f'Elempleo respondió HTTP {offer_response.status} en la oferta.')

      offer_html = await page.content()
      descripcion_md = ElempleoParser.html_to_markdown(offer_html)

      assert descripcion_md, 'La conversión a markdown quedó vacía.'
      assert '<div' not in descripcion_md.lower()
      assert len(descripcion_md) > 200

      await context.close()
      await browser.close()
  except (PlaywrightTimeoutError, PlaywrightError) as error:
    pytest.skip(f'Playwright no pudo completar la navegación real a elempleo: {error}')

