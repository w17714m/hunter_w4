from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from playwright_stealth import Stealth

from src.collectors.linkedin import (
  DEFAULT_PROFILE_DIR,
  DEFAULT_USER_AGENT,
  LinkedInExtractor,
  build_linkedin_search_url,
)

pytestmark = pytest.mark.integration

PROFILE_DIR = Path(os.getenv('LINKEDIN_PROFILE_DIR', str(DEFAULT_PROFILE_DIR)))


@pytest.mark.asyncio
# @pytest.mark.skipif(
#   os.getenv('RUN_INTEGRATION') != '1',
#   reason='Define RUN_INTEGRATION=1 y ejecuta scripts/login_linkedin_persistent.py primero.',
# )
async def test_linkedin_persistent_session_search_and_extract() -> None:
  if not PROFILE_DIR.exists():
    pytest.skip(f'Perfil persistente no encontrado en {PROFILE_DIR}. Ejecuta scripts/login_linkedin_persistent.py primero.')

  search_url = build_linkedin_search_url({'cargo': 'python developer', 'geo_id': '100876405', 'orden': 'reciente'})
  extractor = LinkedInExtractor()

  try:
    playwright = await async_playwright().start()
    try:
      context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        user_agent=DEFAULT_USER_AGENT,
        locale='en-US',
        timezone_id='America/Bogota',
        viewport={'width': 1920, 'height': 1080},
        args=[
          '--disable-blink-features=AutomationControlled',
          '--disable-dev-shm-usage',
          '--no-sandbox',
          '--window-size=1920,1080',
        ],
      )
      context.set_default_timeout(45_000)
    except PlaywrightError as error:
      await playwright.stop()
      message = str(error)
      if 'Executable doesn' in message or 'playwright install' in message:
        pytest.skip('Chromium no instalado. Ejecuta: uv run playwright install chromium')
      raise

    try:
      page = await context.new_page()
      await Stealth().apply_stealth_async(page)

      response = await page.goto(search_url, wait_until='domcontentloaded')
      if response is not None and response.status == 999:
        pytest.skip('LinkedIn devolvió HTTP 999 (bloqueado).')

      body_text = await page.locator('body').inner_text(timeout=5_000)
      state = extractor.detect_block_state(page.url, body_text)
      if state:
        pytest.skip(f'LinkedIn bloqueó la sesión: {state}. Vuelve a ejecutar el script de login.')

      # Extraer IDs directamente del DOM usando _paginate_and_collect del collector
      from src.collectors.linkedin import LinkedInCollector
      collector = LinkedInCollector()
      offer_links = await collector._paginate_and_collect(page, new_urls_needed=50)

      assert offer_links, 'No se encontraron IDs de ofertas. Verifica la sesion.'
      assert len(offer_links) >= 20, (
        f'Se esperaban >=20 IDs en el DOM de LinkedIn, solo se encontraron {len(offer_links)}. '
        'Revisa el selector JOB_CARD_SELECTOR o la carga de la pagina.'
      )

      offer_url = offer_links[0]
      offer_response = await page.goto(offer_url, wait_until='domcontentloaded')
      if offer_response is not None and offer_response.status == 999:
        pytest.skip('LinkedIn bloqueó la oferta con HTTP 999.')

      offer_body = await page.locator('body').inner_text(timeout=5_000)
      offer_state = extractor.detect_block_state(page.url, offer_body)
      if offer_state:
        pytest.skip(f'LinkedIn bloqueó la oferta: {offer_state}.')

      # Esperar a que el JS renderice el bloque de descripción
      from src.collectors.linkedin import DESCRIPTION_SELECTORS
      primary_selector = DESCRIPTION_SELECTORS[0]
      try:
        await page.wait_for_selector(primary_selector, timeout=15_000)
      except Exception:
        pass

      description_html = ''
      for selector in DESCRIPTION_SELECTORS:
        locator = page.locator(selector).first
        if await locator.count() == 0:
          continue
        html = await locator.inner_html(timeout=8_000)
        if html.strip():
          description_html = html
          break

      assert description_html, 'No se encontró bloque de descripción en la oferta.'

      descripcion_md = extractor.description_html_to_markdown(description_html)
      assert descripcion_md, 'La conversión a markdown quedó vacía.'
      assert '<' not in descripcion_md, 'El markdown contiene etiquetas HTML crudas.'
      assert len(descripcion_md) > 200, 'La descripción es demasiado corta para ser válida.'

    finally:
      await context.close()
      await playwright.stop()

  except (PlaywrightTimeoutError, PlaywrightError) as error:
    pytest.skip(f'Playwright no pudo completar la navegación a LinkedIn: {error}')


@pytest.mark.asyncio
@pytest.mark.skipif(
  os.getenv('RUN_INTEGRATION') != '1',
  reason='Define RUN_INTEGRATION=1 para probar reutilización de sesión.',
)
async def test_linkedin_session_reuse_does_not_require_new_login() -> None:
  if not PROFILE_DIR.exists():
    pytest.skip(f'Perfil persistente no encontrado en {PROFILE_DIR}.')

  search_url = build_linkedin_search_url({'cargo': 'backend developer', 'geo_id': '100876405', 'orden': 'reciente'})

  try:
    for run in range(2):
      playwright = await async_playwright().start()
      try:
        context = await playwright.chromium.launch_persistent_context(
          user_data_dir=str(PROFILE_DIR),
          headless=True,
          user_agent=DEFAULT_USER_AGENT,
          locale='en-US',
          timezone_id='America/Bogota',
          viewport={'width': 1366, 'height': 768},
          args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage'],
        )
        context.set_default_timeout(30_000)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        response = await page.goto(search_url, wait_until='domcontentloaded')
        extractor = LinkedInExtractor()
        body_text = await page.locator('body').inner_text(timeout=5_000)
        state = extractor.detect_block_state(page.url, body_text)

        assert state is None, f'Corrida {run + 1}: sesión inválida tras reutilizar perfil: {state}'
        assert response is None or response.status < 400, f'Corrida {run + 1}: HTTP {response.status if response else "None"}'

      finally:
        await context.close()
        await playwright.stop()

  except (PlaywrightTimeoutError, PlaywrightError) as error:
    pytest.skip(f'Playwright no pudo completar la prueba de reutilización: {error}')
