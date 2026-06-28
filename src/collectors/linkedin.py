from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from markdownify import markdownify as md
from playwright.async_api import BrowserContext, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from playwright_stealth import Stealth

from src.stealth.human_delays import between_requests_delay, page_load_delay
from src.core.url_seen_filter import URLSeenFilter
from src.core.visit_budget import VisitBudgetProtocol
from src.stealth.playwright_stealth_extras import expand_description, human_mouse_move_to, random_extra_headers, random_scroll, random_user_agent, random_viewport
from src.stealth.warp_rotator import WarpRotator

logger = logging.getLogger(__name__)

_BLOCK_STATUSES = (999,)


_LINKEDIN_BASE_URL_DEFAULT = 'https://www.linkedin.com'
LINKEDIN_BASE_URL = _LINKEDIN_BASE_URL_DEFAULT  # overridden at runtime via cfg.fuentes
LINKEDIN_JOBS_SEARCH = f'{LINKEDIN_BASE_URL}/jobs/search/'
DEFAULT_PROFILE_DIR = Path('data/playwright/linkedin-profile')
DEFAULT_USER_AGENT = (
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
  'AppleWebKit/537.36 (KHTML, like Gecko) '
  'Chrome/131.0.0.0 Safari/537.36'
)

JOB_CARD_SELECTOR = 'li[data-occludable-job-id]'
# El botón "siguiente" puede tener aria-label en español o en inglés
NEXT_PAGE_SELECTOR = (
  'button[aria-label="Ver siguiente página"],'
  'button[aria-label="View next page"],'
  'button.jobs-search-pagination__button--next'
)
# Texto dentro del span del botón siguiente — se hace click aquí para mayor fiabilidad
NEXT_PAGE_SPAN_SELECTOR = (
  'button[aria-label="Ver siguiente página"] .artdeco-button__text,'
  'button[aria-label="View next page"] .artdeco-button__text,'
  'button.jobs-search-pagination__button--next .artdeco-button__text'
)
PAGE_LOAD_PAUSE_MS = 2_000
MAX_PAGES = 40  # techo de seguridad; el budget de URLs nuevas controla cuándo parar

BLOCK_MARKERS = (
  'authwall',
  'checkpoint',
  'captcha',
  'security verification',
  'unusual traffic',
  'verify you are human',
  'sign in to linkedin',
  'join linkedin',
)

DESCRIPTION_SELECTORS = (
  '[data-testid="expandable-text-box"]',   # LinkedIn nuevo DOM (2025+)
  '.jobs-description__content',             # DOM clásico autenticado
  '.show-more-less-html__markup',           # DOM clásico público
  '.description__text',                     # Variante legacy
)


def normalize_linkedin_url(url: str) -> str:
  absolute = urljoin(LINKEDIN_BASE_URL, url)
  parts = urlsplit(absolute)
  return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def build_linkedin_search_url(item: dict[str, Any], base_url: str = _LINKEDIN_BASE_URL_DEFAULT) -> str:
  from src.config.schemas import LINKEDIN_MODALIDAD_MAP, LINKEDIN_SORT_MAP, LINKEDIN_TIEMPO_PUBLICADO_MAP, LINKEDIN_TIPO_CONTRATO_MAP

  jobs_search = f'{base_url}/jobs/search/'
  params: dict[str, Any] = {'keywords': (item.get('cargo') or '').strip()}

  if geo_id := (item.get('geo_id') or '').strip():
    params['geoId'] = geo_id
  elif ubicacion := (item.get('ubicacion') or '').strip():
    params['location'] = ubicacion

  modalidades: list[str] = item.get('modalidades') or []
  if modalidades:
    params['f_WT'] = ','.join(LINKEDIN_MODALIDAD_MAP[m] for m in modalidades if m in LINKEDIN_MODALIDAD_MAP)

  tiempo = (item.get('tiempo_publicado') or '').strip()
  if tiempo and tiempo in LINKEDIN_TIEMPO_PUBLICADO_MAP:
    params['f_TPR'] = LINKEDIN_TIEMPO_PUBLICADO_MAP[tiempo]

  tipos_contrato: list[str] = item.get('tipos_contrato') or []
  if tipos_contrato:
    params['f_JT'] = ','.join(LINKEDIN_TIPO_CONTRATO_MAP[t] for t in tipos_contrato if t in LINKEDIN_TIPO_CONTRATO_MAP)

  if item.get('easy_apply'):
    params['f_EA'] = 'true'

  orden = (item.get('orden') or 'relevancia').strip()
  params['sortBy'] = LINKEDIN_SORT_MAP.get(orden, 'R')

  return f'{jobs_search}?{urlencode(params)}'


class LinkedInSessionManager:
  def __init__(
    self,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    user_agent: str | None = None,  # None = random per session
    timeout_ms: int = 45_000,
    headless: bool = True,
  ) -> None:
    self.profile_dir = profile_dir
    self.user_agent = user_agent  # if None, a random UA is chosen at context creation time
    self.timeout_ms = timeout_ms
    self.headless = headless

  async def create_context(self, playwright: Any) -> BrowserContext:
    self.profile_dir.mkdir(parents=True, exist_ok=True)
    ua = self.user_agent or random_user_agent()
    viewport = random_viewport()
    context: BrowserContext = await playwright.chromium.launch_persistent_context(
      user_data_dir=str(self.profile_dir),
      headless=self.headless,
      user_agent=ua,
      locale='en-US',
      timezone_id='America/Bogota',
      viewport=viewport,
      extra_http_headers=random_extra_headers(),
      args=[
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
      ],
    )
    context.set_default_timeout(self.timeout_ms)
    return context


class LinkedInExtractor:
  def extract_offer_links(self, html: str, base_url: str = _LINKEDIN_BASE_URL_DEFAULT) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    seen: set[str] = set()
    links: list[str] = []

    # Estrategia 1: IDs desde data-occludable-job-id — presentes en TODOS los <li>
    # del DOM desde la carga inicial, incluso en los placeholders no renderizados.
    # Esto nos da los 25 IDs por página sin necesitar scroll.
    for li in soup.select('li[data-occludable-job-id]'):
      job_id = (li.get('data-occludable-job-id') or '').strip()
      if not job_id:
        continue
      url = f'{base_url}/jobs/view/{job_id}'
      if url in seen:
        continue
      seen.add(url)
      links.append(url)

    # Estrategia 2: anchors /jobs/view/ como fallback si no hay data-occludable-job-id
    if not links:
      for anchor in soup.select('a[href*="/jobs/view/"]'):
        href = (anchor.get('href') or '').strip()
        if not href:
          continue
        url = normalize_linkedin_url(href)
        if url in seen:
          continue
        seen.add(url)
        links.append(url)

    return links

  def description_html_to_markdown(self, description_html: str) -> str:
    return md(description_html, heading_style='ATX').strip()

  def detect_block_state(self, url: str, body_text: str) -> str | None:
    lower_url = url.lower()
    lower_body = body_text.lower()
    for marker in BLOCK_MARKERS:
      if marker in lower_url or marker in lower_body:
        if 'captcha' in marker or 'verify' in marker or 'verification' in marker:
          return 'captcha'
        if 'authwall' in marker or 'sign in' in marker or 'join' in marker or 'login' in marker:
          return 'login_required'
        return 'blocked'
    if response_is_999 := '999' in lower_url:
      _ = response_is_999
      return 'blocked'
    return None


class LinkedInCollector:
  def __init__(
    self,
    session_manager: LinkedInSessionManager | None = None,
    extractor: LinkedInExtractor | None = None,
    timeout_ms: int = 45_000,
    max_offers_per_search: int = 125,  # 5 páginas × 25 ofertas/página
    headless: bool = True,
    warp_rotator: WarpRotator | None = None,
    max_ip_rotations: int = 2,
    url_filter: URLSeenFilter | None = None,
    visit_budget: VisitBudgetProtocol | None = None,
    base_url: str = _LINKEDIN_BASE_URL_DEFAULT,
  ) -> None:
    self.session_manager = session_manager or LinkedInSessionManager(timeout_ms=timeout_ms, headless=headless)
    self.extractor = extractor or LinkedInExtractor()
    self.timeout_ms = timeout_ms
    self.max_offers_per_search = max_offers_per_search
    self.warp_rotator = warp_rotator
    self.max_ip_rotations = max_ip_rotations
    self.url_filter = url_filter
    self.visit_budget = visit_budget
    self.base_url = base_url

  async def _try_rotate(self) -> bool:
    """Rotate IP via WARP. Returns True on success, False if WARP is unavailable."""
    if self.warp_rotator is None:
      logger.warning('[LinkedIn] Bloqueo detectado pero warp_rotator no está configurado — sin rotación de IP')
      return False
    rotated = await self.warp_rotator.rotate()
    if not rotated:
      logger.warning('[LinkedIn] Rotación de IP solicitada pero falló o WARP no está disponible')
    return rotated

  async def _new_page(self, playwright: Any, context_holder: list[Any]) -> Any:
    """Cierra el contexto actual (si existe), abre uno nuevo y retorna la página lista.

    context_holder es una lista de un elemento que actúa como referencia mutable
    al contexto activo, permitiendo reemplazarlo sin retornar múltiples valores.
    """
    if context_holder:
      try:
        await context_holder[0].close()
      except Exception:  # noqa: BLE001
        pass
      context_holder.clear()

    context = await self.session_manager.create_context(playwright)
    context_holder.append(context)
    page = await context.new_page()
    await Stealth().apply_stealth_async(page)
    logger.info('[LinkedIn] Nuevo contexto de navegador abierto')
    return page

  def build_search_urls(self, busquedas_linkedin: list[dict[str, Any]]) -> list[str]:
    return [build_linkedin_search_url(item, base_url=self.base_url) for item in busquedas_linkedin]

  async def collect(self, busquedas_linkedin: list[dict[str, str]]) -> list[dict[str, Any]]:
    search_urls = self.build_search_urls(busquedas_linkedin)
    if not search_urls:
      return []

    results: list[dict[str, Any]] = []
    playwright = await async_playwright().start()
    context_holder: list[Any] = []

    try:
      try:
        page = await self._new_page(playwright, context_holder)
      except PlaywrightError as error:
        message = str(error)
        if 'Executable doesn' in message or 'playwright install' in message:
          return [self._build_error_result('', 'blocked', 'PLAYWRIGHT_BROWSER_MISSING')]
        return [self._build_error_result('', 'blocked', message)]

      for search_url in search_urls:
        search_result, page = await self._collect_search(playwright, context_holder, page, search_url)
        results.extend(search_result)

      return results
    finally:
      if context_holder:
        try:
          await context_holder[0].close()
        except Exception:  # noqa: BLE001
          pass
      await playwright.stop()

  async def _collect_search(
    self,
    playwright: Any,
    context_holder: list[Any],
    page: Any,
    search_url: str,
  ) -> tuple[list[dict[str, Any]], Any]:
    """Procesa una URL de búsqueda con reintentos completos (rotación IP + nuevo contexto).

    Retorna (resultados, página_activa) — la página puede haber cambiado si se
    reabrió el contexto durante un reintento.
    """
    if self.visit_budget is not None and self.visit_budget.exhausted():
      logger.info('[LinkedIn] Presupuesto agotado antes de iniciar búsqueda: %s', search_url)
      return [], page

    for attempt in range(self.max_ip_rotations + 1):
      try:
        response = await page.goto(search_url, wait_until='domcontentloaded')

        # Bloqueo HTTP duro (999)
        if response is not None and response.status in _BLOCK_STATUSES:
          logger.warning('[LinkedIn] HTTP %d en búsqueda (intento %d): %s', response.status, attempt + 1, search_url)
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
          if page is None:
            return [self._build_error_result(search_url, 'blocked', f'HTTP 999 tras {attempt + 1} intentos')], await self._new_page(playwright, context_holder)
          continue

        body_text = await page.locator('body').inner_text(timeout=5_000)
        state = self.extractor.detect_block_state(page.url, body_text)

        # Bloqueo por contenido (authwall, captcha, etc.)
        if state:
          logger.warning('[LinkedIn] Bloqueo por contenido (%s) en búsqueda (intento %d): %s', state, attempt + 1, search_url)
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
          if page is None:
            return [self._build_error_result(search_url, state, f'Bloqueo {state} tras {attempt + 1} intentos')], await self._new_page(playwright, context_holder)
          continue

        # Sin bloqueo: extraer ofertas nuevas (filtro integrado en paginación)
        new_urls_needed = self.visit_budget.remaining() if self.visit_budget is not None else self.max_offers_per_search
        offer_links = await self._paginate_and_collect(page, new_urls_needed, url_filter=self.url_filter)
        logger.info('[LinkedIn] %d URLs nuevas para visitar desde: %s', len(offer_links), search_url)

        results: list[dict[str, Any]] = []
        for offer_url in offer_links:
          if self.visit_budget is not None and not self.visit_budget.consume():
            logger.warning(
              '[LinkedIn] Presupuesto de visitas agotado (%d/%d). Deteniendo scraping.',
              self.visit_budget.consumed(),
              self.visit_budget.consumed() + self.visit_budget.remaining(),
            )
            break
          result, page = await self._fetch_offer_with_retry(playwright, context_holder, page, offer_url)
          results.append(result)
        return results, page

      except (PlaywrightTimeoutError, PlaywrightError) as error:
        logger.warning('[LinkedIn] Error Playwright en búsqueda (intento %d): %s', attempt + 1, error)
        if attempt < self.max_ip_rotations:
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
        else:
          return [self._build_error_result(search_url, 'blocked', str(error))], await self._new_page(playwright, context_holder)

    return [self._build_error_result(search_url, 'blocked', f'Agotados {self.max_ip_rotations + 1} intentos')], await self._new_page(playwright, context_holder)

  async def _rotate_and_reopen(
    self,
    playwright: Any,
    context_holder: list[Any],
    url: str,
    attempt: int,
  ) -> Any | None:
    """Rota IP con WARP y abre un nuevo contexto de navegador.

    Retorna la nueva página si la rotación tuvo éxito, None si WARP no está
    disponible o falló (para que el caller decida si abortar o abrir contexto limpio).
    """
    rotated = await self._try_rotate()
    if rotated:
      logger.info('[LinkedIn] IP rotada OK (intento %d) — reabriendo contexto para: %s', attempt + 1, url)
      await between_requests_delay()
      return await self._new_page(playwright, context_holder)
    else:
      # WARP no disponible: abrir al menos un contexto limpio para limpiar cookies/fingerprint
      logger.warning('[LinkedIn] WARP no disponible — reabriendo contexto sin rotación de IP (intento %d)', attempt + 1)
      await between_requests_delay()
      return await self._new_page(playwright, context_holder)

  async def _fetch_offer_with_retry(
    self,
    playwright: Any,
    context_holder: list[Any],
    page: Any,
    offer_url: str,
  ) -> tuple[dict[str, Any], Any]:
    """Extrae una oferta individual con reintentos y reapertura de contexto ante bloqueos."""
    for attempt in range(self.max_ip_rotations + 1):
      try:
        response = await page.goto(offer_url, wait_until='domcontentloaded')

        if response is not None and response.status in _BLOCK_STATUSES:
          logger.warning('[LinkedIn] HTTP %d en oferta (intento %d): %s', response.status, attempt + 1, offer_url)
          if attempt < self.max_ip_rotations:
            page = await self._rotate_and_reopen(playwright, context_holder, offer_url, attempt)
            continue
          return self._build_error_result(offer_url, 'blocked', f'HTTP 999 tras {attempt + 1} intentos'), page

        body_text = await page.locator('body').inner_text(timeout=5_000)
        state = self.extractor.detect_block_state(page.url, body_text)
        if state:
          logger.warning('[LinkedIn] Bloqueo %s en oferta (intento %d): %s', state, attempt + 1, offer_url)
          if attempt < self.max_ip_rotations:
            page = await self._rotate_and_reopen(playwright, context_holder, offer_url, attempt)
            continue
          return self._build_error_result(offer_url, state, f'Bloqueo {state} tras {attempt + 1} intentos'), page

        await random_scroll(page)
        description_html, extraction_status = await self._extract_description_html(page)
        if not description_html:
          return self._build_error_result(offer_url, 'empty_description', 'No se encontró bloque de descripción'), page

        descripcion_md = self.extractor.description_html_to_markdown(description_html)
        if not descripcion_md:
          return self._build_error_result(offer_url, 'empty_description', 'Markdown vacío tras conversión'), page

        titulo = await self._extract_text(page, ['h1', '.jobs-unified-top-card__job-title', '.top-card-layout__title'])
        empresa = await self._extract_text(page, ['.jobs-unified-top-card__company-name a', '.topcard__org-name-link', '.top-card-layout__card a'])
        ubicacion = await self._extract_text(page, ['.jobs-unified-top-card__bullet', '.topcard__flavor--bullet'])

        return {
          'url': normalize_linkedin_url(offer_url),
          'titulo': titulo or 'Sin titulo',
          'empresa': empresa,
          'ubicacion': ubicacion,
          'descripcion_md': descripcion_md,
          'fuente': 'linkedin',
          'scraped_at': datetime.now(UTC).isoformat(),
          'extraction_status': extraction_status,
        }, page

      except (PlaywrightTimeoutError, PlaywrightError) as error:
        logger.warning('[LinkedIn] Error Playwright en oferta (intento %d): %s — %s', attempt + 1, offer_url, error)
        if attempt < self.max_ip_rotations:
          page = await self._rotate_and_reopen(playwright, context_holder, offer_url, attempt)
        else:
          page = await self._new_page(playwright, context_holder)
          return self._build_error_result(offer_url, 'blocked', str(error)), page

    page = await self._new_page(playwright, context_holder)
    return self._build_error_result(offer_url, 'blocked', f'Agotados {self.max_ip_rotations + 1} intentos'), page

  async def _paginate_and_collect(
    self,
    page: Any,
    new_urls_needed: int,
    url_filter: URLSeenFilter | None = None,
  ) -> list[str]:
    """Pagina LinkedIn hasta encontrar new_urls_needed URLs no vistas en DB.

    El filtro se aplica página a página para que la condición de parada sea
    "suficientes URLs nuevas", no "suficientes URLs totales". Esto permite
    seguir paginando cuando la mayoría de ofertas ya fueron procesadas.
    """
    new_links: list[str] = []
    seen_local: set[str] = set()

    for page_num in range(MAX_PAGES):
      page_ids = await self._wait_and_extract_ids(page)
      page_urls: list[str] = []
      for job_id in page_ids:
        url = f'{self.base_url}/jobs/view/{job_id}'
        if url not in seen_local:
          seen_local.add(url)
          page_urls.append(url)

      if url_filter and page_urls:
        already_seen = url_filter.bulk_seen('linkedin', page_urls)
        new_on_page = [u for u in page_urls if u not in already_seen]
        if already_seen:
          logger.info(
            '[LinkedIn] Página %d: %d/%d URLs ya procesadas',
            page_num + 1, len(already_seen), len(page_urls),
          )
      else:
        new_on_page = page_urls

      new_links.extend(new_on_page)
      logger.info('[LinkedIn] Página %d: %d nuevas acumuladas de %d objetivo', page_num + 1, len(new_links), new_urls_needed)

      if len(new_links) >= new_urls_needed:
        break

      if page_num < MAX_PAGES - 1:
        went_next = await self._click_next_page(page)
        if not went_next:
          break
        await page_load_delay()

    logger.info('[LinkedIn] Paginación completada: %d URLs nuevas encontradas', len(new_links))
    return new_links[:new_urls_needed]

  async def _wait_and_extract_ids(self, page: Any) -> list[str]:
    """Espera a que los <li[data-occludable-job-id]> se estabilicen y retorna sus IDs.

    Deja propagar PlaywrightTimeoutError intencionalmente para que _collect_search
    active el mecanismo de reintento con reapertura de contexto.
    """
    await page.wait_for_selector(JOB_CARD_SELECTOR, timeout=10_000)

    # LinkedIn carga los <li> en dos batches vía XHR; esperar a que el conteo se estabilice
    prev_count = -1
    for _ in range(15):
      count: int = await page.evaluate(
        "() => document.querySelectorAll('li[data-occludable-job-id]').length"
      )
      if count == prev_count and count > 0:
        break
      prev_count = count
      await asyncio.sleep(0.8)

    return await page.evaluate("""
      () => {
        const items = document.querySelectorAll('li[data-occludable-job-id]');
        return [...items].map(li => li.getAttribute('data-occludable-job-id')).filter(Boolean);
      }
    """)

  async def _click_next_page(self, page: Any) -> bool:
    """Click the next-page button span.  Returns True on success."""
    try:
      # Click on the inner span — more reliable than clicking the outer button
      span = page.locator(NEXT_PAGE_SPAN_SELECTOR).first
      if await span.count() == 0:
        return False
      btn = span.locator('xpath=..')  # parent button
      is_disabled = await btn.get_attribute('disabled')
      if is_disabled is not None:
        return False
      await human_mouse_move_to(page, span)
      await span.click()
      return True
    except (PlaywrightTimeoutError, PlaywrightError):
      return False

  async def _extract_description_html(self, page: Any) -> tuple[str, str]:
    try:
      await page.wait_for_selector(DESCRIPTION_SELECTORS[0], timeout=15_000)
    except (PlaywrightTimeoutError, PlaywrightError):
      pass

    # Expand truncated description before extracting HTML
    await expand_description(page)

    for selector in DESCRIPTION_SELECTORS:
      try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
          continue
        html = await locator.inner_html(timeout=8_000)
        if html.strip():
          return html, 'ok'
      except (PlaywrightTimeoutError, PlaywrightError):
        continue
    return '', 'empty_description'

  @staticmethod
  async def _extract_text(page: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
      try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
          continue
        text = ' '.join((await locator.inner_text(timeout=5_000)).split())
        if text:
          return text
      except (PlaywrightTimeoutError, PlaywrightError):
        continue
    return None

  @staticmethod
  def _build_error_result(url: str, extraction_status: str, error: str) -> dict[str, Any]:
    return {
      'url': url,
      'fuente': 'linkedin',
      'titulo': None,
      'empresa': None,
      'ubicacion': None,
      'descripcion_md': 'No disponible por error de extraccion.',
      'scraped_at': datetime.now(UTC).isoformat(),
      'extraction_status': extraction_status,
      'error': error,
    }
