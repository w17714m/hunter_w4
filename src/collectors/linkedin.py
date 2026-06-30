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
from src.core.db import SQLiteOfferRepository
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
# "Next" button aria-label may appear in Spanish or English depending on the user's locale
NEXT_PAGE_SELECTOR = (
  'button[aria-label="Ver siguiente página"],'
  'button[aria-label="View next page"],'
  'button.jobs-search-pagination__button--next'
)
# Text inside the next-button span — clicking here is more reliable than the outer button
NEXT_PAGE_SPAN_SELECTOR = (
  'button[aria-label="Ver siguiente página"] .artdeco-button__text,'
  'button[aria-label="View next page"] .artdeco-button__text,'
  'button.jobs-search-pagination__button--next .artdeco-button__text'
)
PAGE_LOAD_PAUSE_MS = 2_000
MAX_PAGES = 40  # safety ceiling; the new-URL budget controls when pagination actually stops

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

# These markers appear in LinkedIn's authenticated footer/header even on valid job pages.
# When the URL is a /jobs/view/ offer page, they are footer noise — not real blocks.
_FOOTER_NOISE_MARKERS = frozenset({'sign in to linkedin', 'join linkedin'})

DESCRIPTION_SELECTORS = (
  '[data-testid="expandable-text-box"]',   # LinkedIn nuevo DOM (2025+)
  '.jobs-description__content',             # classic authenticated DOM
  '.show-more-less-html__markup',           # classic public DOM
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
    self.user_agent = user_agent  # None → random UA chosen at context creation time
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

    # Strategy 1: IDs from data-occludable-job-id — present on ALL <li> elements
    # from initial page load, including unrendered placeholders.
    # Yields all 25 IDs per page without requiring a scroll.
    for li in soup.select('li[data-occludable-job-id]'):
      job_id = (li.get('data-occludable-job-id') or '').strip()
      if not job_id:
        continue
      url = f'{base_url}/jobs/view/{job_id}'
      if url in seen:
        continue
      seen.add(url)
      links.append(url)

    # Strategy 2: /jobs/view/ anchors as fallback when data-occludable-job-id is absent
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

  def detect_block_state(self, url: str, body_text: str, is_offer_page: bool = False) -> str | None:
    lower_url = url.lower()
    lower_body = body_text.lower()
    for marker in BLOCK_MARKERS:
      # On authenticated offer pages, footer markers are noise — only block on URL match
      if is_offer_page and marker in _FOOTER_NOISE_MARKERS and marker not in lower_url:
        continue
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
    max_offers_per_search: int = 125,  # 5 pages × 25 offers/page
    headless: bool = True,
    warp_rotator: WarpRotator | None = None,
    max_ip_rotations: int = 2,
    url_filter: URLSeenFilter | None = None,
    visit_budget: VisitBudgetProtocol | None = None,
    base_url: str = _LINKEDIN_BASE_URL_DEFAULT,
    ollama_base_url: str = 'http://localhost:11434',
    extractor_html_model: str = 'deepseek-r1:14b',
    extractor_company_model: str = 'qwen3:8b',
    repo: SQLiteOfferRepository | None = None,
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
    self.ollama_base_url = ollama_base_url
    self.extractor_html_model = extractor_html_model
    self.extractor_company_model = extractor_company_model
    self._repo = repo

  async def _try_rotate(self) -> bool:
    """Rotate IP via WARP. Returns True on success, False if WARP is unavailable."""
    if self.warp_rotator is None:
      logger.warning('[LinkedIn] Block detected but warp_rotator is not configured — no IP rotation')
      return False
    rotated = await self.warp_rotator.rotate()
    if not rotated:
      logger.warning('[LinkedIn] IP rotation requested but failed or WARP is not available')
    return rotated

  async def _new_page(self, playwright: Any, context_holder: list[Any]) -> Any:
    """Close the current context (if any), open a new one, and return a ready page.

    context_holder is a single-element list that acts as a mutable reference to the
    active context, allowing replacement without returning multiple values.
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
    """Process a search URL with full retries (IP rotation + new context).

    Returns (results, active_page) — the page may have changed if the context
    was reopened during a retry attempt.
    """
    if self.visit_budget is not None and self.visit_budget.exhausted():
      logger.info('[LinkedIn] Budget exhausted before starting search: %s', search_url)
      return [], page

    for attempt in range(self.max_ip_rotations + 1):
      try:
        response = await page.goto(search_url, wait_until='domcontentloaded')

        # Hard HTTP block (999)
        if response is not None and response.status in _BLOCK_STATUSES:
          logger.warning('[LinkedIn] HTTP %d on search (attempt %d): %s', response.status, attempt + 1, search_url)
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
          if page is None:
            return [self._build_error_result(search_url, 'blocked', f'HTTP 999 tras {attempt + 1} intentos')], await self._new_page(playwright, context_holder)
          continue

        body_text = await page.locator('body').inner_text(timeout=5_000)
        state = self.extractor.detect_block_state(page.url, body_text)

        # Content-based block (authwall, captcha, etc.)
        if state:
          logger.warning('[LinkedIn] Content block (%s) on search (attempt %d): %s', state, attempt + 1, search_url)
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
          if page is None:
            return [self._build_error_result(search_url, state, f'Block {state} after {attempt + 1} attempts')], await self._new_page(playwright, context_holder)
          continue

        # No block: extract new offers (filter integrated in pagination)
        new_urls_needed = self.visit_budget.remaining() if self.visit_budget is not None else self.max_offers_per_search
        offer_pairs = await self._paginate_and_collect(page, new_urls_needed, url_filter=self.url_filter)
        logger.info('[LinkedIn] %d URLs nuevas para visitar desde: %s', len(offer_pairs), search_url)

        results: list[dict[str, Any]] = []
        for offer_url, empresa_card in offer_pairs:
          # Check blacklist before visiting the offer detail page
          if empresa_card and self._repo is not None and self._repo.is_blacklisted(empresa_card):
            logger.info('[LinkedIn] Empresa en lista negra, omitiendo oferta: empresa=%s url=%s', empresa_card, offer_url)
            results.append(self._build_error_result(offer_url, 'blacklisted', f'Empresa en lista negra: {empresa_card}'))
            continue

          if self.visit_budget is not None and not self.visit_budget.consume():
            logger.warning(
              '[LinkedIn] Visit budget exhausted (%d/%d). Stopping scraping.',
              self.visit_budget.consumed(),
              self.visit_budget.consumed() + self.visit_budget.remaining(),
            )
            break
          result, page = await self._fetch_offer_with_retry(playwright, context_holder, page, offer_url)

          # Update empresa in SQLite if the card had a name and the result didn't resolve it
          if empresa_card and self._repo is not None and result.get('empresa') is None:
            result['empresa'] = empresa_card
          results.append(result)
        return results, page

      except (PlaywrightTimeoutError, PlaywrightError) as error:
        logger.warning('[LinkedIn] Playwright error on search (attempt %d): %s', attempt + 1, error)
        if attempt < self.max_ip_rotations:
          page = await self._rotate_and_reopen(playwright, context_holder, search_url, attempt)
        else:
          return [self._build_error_result(search_url, 'blocked', str(error))], await self._new_page(playwright, context_holder)

    return [self._build_error_result(search_url, 'blocked', f'All {self.max_ip_rotations + 1} attempts exhausted')], await self._new_page(playwright, context_holder)

  async def _rotate_and_reopen(
    self,
    playwright: Any,
    context_holder: list[Any],
    url: str,
    attempt: int,
  ) -> Any | None:
    """Rotate the IP via WARP and open a new browser context.

    Returns the new page if rotation succeeded, None if WARP is unavailable or
    failed (caller decides whether to abort or open a clean context).
    """
    rotated = await self._try_rotate()
    if rotated:
      logger.info('[LinkedIn] IP rotada OK (intento %d) — reabriendo contexto para: %s', attempt + 1, url)
      await between_requests_delay()
      return await self._new_page(playwright, context_holder)
    else:
      # WARP unavailable: open a clean context at minimum to clear cookies/fingerprint
      logger.warning('[LinkedIn] WARP unavailable — reopening context without IP rotation (attempt %d)', attempt + 1)
      await between_requests_delay()
      return await self._new_page(playwright, context_holder)

  async def _fetch_offer_with_retry(
    self,
    playwright: Any,
    context_holder: list[Any],
    page: Any,
    offer_url: str,
  ) -> tuple[dict[str, Any], Any]:
    """Extract a single offer with retries and context reopening on blocks."""
    prev_body_len: int | None = None  # detect persistent block by identical body size
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
        is_offer_page = '/jobs/view/' in page.url
        logger.info('[LinkedIn] Página cargada (intento %d) | url_final=%s | is_offer_page=%s | body_len=%d', attempt + 1, page.url, is_offer_page, len(body_text))
        state = self.extractor.detect_block_state(page.url, body_text, is_offer_page=is_offer_page)
        if state:
          logger.warning('[LinkedIn] Bloqueo %s en oferta (intento %d): %s', state, attempt + 1, offer_url)
          logger.debug('[LinkedIn] Body snippet (300 chars): %s', body_text[:300].replace('\n', ' '))

          # Heuristic block detection can false-positive (e.g. a new layout that
          # happens to contain a BLOCK_MARKERS string, or partially-rendered content).
          # Before burning an IP rotation, ask the reasoning LLM to verify whether
          # real job content is actually present on this page.
          verified = await self._verify_block_with_llm(page, offer_url, attempt)
          if verified is not None:
            description_html, extraction_status = verified
            descripcion_md = self.extractor.description_html_to_markdown(description_html)
            if descripcion_md:
              titulo = await self._extract_text(page, ['h1', '.jobs-unified-top-card__job-title', '.top-card-layout__title'])
              empresa = await self._extract_text(page, ['.jobs-unified-top-card__company-name a', '.topcard__org-name-link', '.top-card-layout__card a'])
              ubicacion = await self._extract_text(page, ['.jobs-unified-top-card__bullet', '.topcard__flavor--bullet'])
              return {
                'url': normalize_linkedin_url(offer_url),
                'titulo': titulo or 'No title',
                'empresa': empresa,
                'ubicacion': ubicacion,
                'descripcion_md': descripcion_md,
                'fuente': 'linkedin',
                'scraped_at': datetime.now(UTC).isoformat(),
                'extraction_status': extraction_status,
              }, page

          # If body size is identical across attempts, this offer is individually rate-limited
          # by LinkedIn and IP rotation will not help — abandon immediately.
          if prev_body_len is not None and len(body_text) == prev_body_len:
            logger.warning('[LinkedIn] Body idéntico en intentos consecutivos (len=%d) — bloqueo por job ID, abandonando sin más rotaciones: %s', prev_body_len, offer_url)
            return self._build_error_result(offer_url, state, f'Bloqueo persistente por job ID tras {attempt + 1} intentos'), page
          prev_body_len = len(body_text)
          if attempt < self.max_ip_rotations:
            page = await self._rotate_and_reopen(playwright, context_holder, offer_url, attempt)
            continue
          return self._build_error_result(offer_url, state, f'Block {state} after {attempt + 1} attempts'), page

        logger.info('[LinkedIn] Sin bloqueo detectado — iniciando extracción de descripción')
        await random_scroll(page)
        description_html, extraction_status = await self._extract_description_html(page)
        logger.info('[LinkedIn] _extract_description_html completó | status=%s | html_len=%d', extraction_status, len(description_html))
        if not description_html:
          return self._build_error_result(offer_url, 'empty_description', 'Description block not found'), page

        descripcion_md = self.extractor.description_html_to_markdown(description_html)
        if not descripcion_md:
          return self._build_error_result(offer_url, 'empty_description', 'Empty markdown after conversion'), page

        titulo = await self._extract_text(page, ['h1', '.jobs-unified-top-card__job-title', '.top-card-layout__title'])
        empresa = await self._extract_text(page, ['.jobs-unified-top-card__company-name a', '.topcard__org-name-link', '.top-card-layout__card a'])
        ubicacion = await self._extract_text(page, ['.jobs-unified-top-card__bullet', '.topcard__flavor--bullet'])

        return {
          'url': normalize_linkedin_url(offer_url),
          'titulo': titulo or 'No title',
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
    return self._build_error_result(offer_url, 'blocked', f'All {self.max_ip_rotations + 1} attempts exhausted'), page

  async def _paginate_and_collect(
    self,
    page: Any,
    new_urls_needed: int,
    url_filter: URLSeenFilter | None = None,
  ) -> list[tuple[str, str]]:
    """Paginate LinkedIn until new_urls_needed unseen URLs are found.

    Returns list of (url, empresa) tuples. empresa may be empty string if not found.
    Company names are extracted by LLM from card HTML — no hardcoded CSS selectors.
    The filter is applied page by page so the stop condition is "enough new URLs",
    not "enough total URLs".
    """
    from src.stealth.company_extractor import CompanyExtractor
    company_extractor = CompanyExtractor(
      base_url=self.ollama_base_url,
      model=self.extractor_company_model,
    )

    new_links: list[tuple[str, str]] = []
    seen_local: set[str] = set()

    for page_num in range(MAX_PAGES):
      page_cards = await self._wait_and_extract_ids(page)
      page_items: list[tuple[str, str, str]] = []  # (url, empresa, card_html)
      for card in page_cards:
        url = f'{self.base_url}/jobs/view/{card["id"]}'
        if url not in seen_local:
          seen_local.add(url)
          page_items.append((url, '', card.get('card_html', '')))

      if url_filter and page_items:
        page_urls = [u for u, _, _ in page_items]
        already_seen = url_filter.bulk_seen('linkedin', page_urls)
        new_on_page = [(u, e, h) for u, e, h in page_items if u not in already_seen]
        if already_seen:
          logger.info(
            '[LinkedIn] Page %d: %d/%d URLs already processed',
            page_num + 1, len(already_seen), len(page_items),
          )
      else:
        new_on_page = page_items

      # Extract company names in parallel via LLM for new cards only
      if new_on_page:
        logger.info('[LinkedIn] Extrayendo empresa de %d cards via LLM (paralelo)', len(new_on_page))
        empresa_results: list[str] = list(await asyncio.gather(*[
          asyncio.to_thread(company_extractor.extract, card_html)
          for _, _, card_html in new_on_page
        ]))
        new_links.extend(
          (url, empresa)
          for (url, _, _), empresa in zip(new_on_page, empresa_results)
        )
        for (url, _, _), empresa in zip(new_on_page, empresa_results):
          if empresa:
            logger.info('[LinkedIn] Card empresa extraída por LLM: "%s" → %s', empresa, url)

      logger.info('[LinkedIn] Page %d: %d new accumulated of %d target', page_num + 1, len(new_links), new_urls_needed)

      if len(new_links) >= new_urls_needed:
        break

      if page_num < MAX_PAGES - 1:
        went_next = await self._click_next_page(page)
        if not went_next:
          break
        await page_load_delay()

    logger.info('[LinkedIn] Pagination complete: %d new URLs found', len(new_links))
    return new_links[:new_urls_needed]

  async def _wait_and_extract_ids(self, page: Any) -> list[dict[str, str]]:
    """Wait for <li[data-occludable-job-id]> elements to stabilize and return cards.

    Each card is a dict with 'id' (job ID) and 'card_html' (outerHTML of the <li>).
    The caller uses card_html to extract the company name via LLM without relying
    on hardcoded CSS selectors that LinkedIn rotates.
    PlaywrightTimeoutError is intentionally allowed to propagate so _collect_search
    can trigger the retry mechanism with context reopening.
    """
    await page.wait_for_selector(JOB_CARD_SELECTOR, timeout=10_000)

    # LinkedIn loads <li> elements in two XHR batches; wait for the count to stabilize
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
        return [...items].map(li => {
          const id = li.getAttribute('data-occludable-job-id') || '';
          if (!id) return null;
          return {id, card_html: li.outerHTML};
        }).filter(Boolean);
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

  async def _verify_block_with_llm(self, page: Any, offer_url: str, attempt: int) -> tuple[str, str] | None:
    """Ask the reasoning LLM to double-check a heuristic block before rotating IP.

    detect_block_state() is a plain string-match heuristic and can false-positive
    (new layout containing a BLOCK_MARKERS substring, partially-rendered content,
    etc). Returns (description_html, extraction_status) if the LLM finds real job
    content despite the block heuristic firing, or None if it confirms there is
    nothing extractable — in which case the caller proceeds with IP rotation as before.
    """
    logger.info('[LinkedIn][verify] Bloqueo detectado (intento %d) — verificando con LLM antes de rotar IP: %s', attempt + 1, offer_url)
    try:
      from src.stealth.html_description_extractor import HTMLDescriptionExtractor
      page_html = await page.content()
      llm_extractor = HTMLDescriptionExtractor(
        base_url=self.ollama_base_url,
        model=self.extractor_html_model,
      )
      result = await asyncio.to_thread(llm_extractor.extract, page_html)
      logger.info(
        '[LinkedIn][verify] LLM respondió | description_text_len=%d | expand_selector="%s"',
        len(result.get('description_text', '')), result.get('expand_selector', ''),
      )

      if result.get('description_text'):
        logger.info('[LinkedIn][verify] Falso positivo confirmado — LLM encontró descripción real pese al bloqueo heurístico')
        if result.get('expand_selector') and self._repo is not None:
          self._repo.kv_set('linkedin_expand_selector', result['expand_selector'])
        return result['description_text'], 'ok_llm'

      if result.get('expand_selector'):
        selector = result['expand_selector']
        try:
          btn = page.locator(selector).first
          if await btn.count() > 0:
            await btn.click(force=True)
            await asyncio.sleep(0.8)
            for sel in DESCRIPTION_SELECTORS:
              try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                  continue
                html = await loc.inner_html(timeout=8_000)
                if html.strip():
                  logger.info('[LinkedIn][verify] Falso positivo confirmado — click LLM-guiado exitoso pese al bloqueo heurístico')
                  if self._repo is not None:
                    self._repo.kv_set('linkedin_expand_selector', selector)
                  return html, 'ok_llm'
              except (PlaywrightTimeoutError, PlaywrightError):
                continue
        except Exception as exc:  # noqa: BLE001
          logger.debug('[LinkedIn][verify] Excepción al usar selector LLM en página bloqueada: %s', exc)

      logger.info('[LinkedIn][verify] LLM confirma que no hay contenido extraíble — bloqueo real, procediendo a rotar IP')
      return None
    except Exception as exc:  # noqa: BLE001
      logger.warning('[LinkedIn][verify] Verificación LLM falló silenciosamente: %s', exc)
      return None

  async def _extract_description_html(self, page: Any) -> tuple[str, str]:
    logger.info('[LinkedIn][extract] Paso 1: wait_for_selector "%s" (timeout 15s)', DESCRIPTION_SELECTORS[0])
    try:
      await page.wait_for_selector(DESCRIPTION_SELECTORS[0], timeout=15_000)
      logger.info('[LinkedIn][extract] Paso 1: selector primario encontrado en DOM')
    except (PlaywrightTimeoutError, PlaywrightError):
      logger.info('[LinkedIn][extract] Paso 1: selector primario NO encontrado en 15s — continuando')

    logger.info('[LinkedIn][extract] Paso 2: expand_description() — buscando botón "ver más"')
    expanded = await expand_description(page)
    logger.info('[LinkedIn][extract] Paso 2: expand_description() retornó %s', expanded)

    logger.info('[LinkedIn][extract] Paso 3: iterando %d selectores hardcodeados', len(DESCRIPTION_SELECTORS))
    for selector in DESCRIPTION_SELECTORS:
      try:
        locator = page.locator(selector).first
        count = await locator.count()
        logger.debug('[LinkedIn][extract] Selector "%s" → count=%d', selector, count)
        if count == 0:
          continue
        html = await locator.inner_html(timeout=8_000)
        if html.strip():
          logger.info('[LinkedIn][extract] Paso 3: éxito con selector "%s" (html_len=%d)', selector, len(html))
          return html, 'ok'
        logger.debug('[LinkedIn][extract] Selector "%s" encontrado pero HTML vacío', selector)
      except (PlaywrightTimeoutError, PlaywrightError):
        logger.debug('[LinkedIn][extract] Selector "%s" → timeout/error Playwright', selector)
        continue
    logger.warning('[LinkedIn][extract] Paso 3: ningún selector hardcodeado produjo HTML')

    # --- Selector guardado en SQLite (descubierto por el razonador en una sesión previa) ---
    saved_selector: str | None = None
    if self._repo is not None:
      saved_selector = self._repo.kv_get('linkedin_expand_selector')
      logger.info('[LinkedIn][extract] Paso 4: selector en DB → %s', saved_selector or 'ninguno')
    else:
      logger.info('[LinkedIn][extract] Paso 4: repo no configurado, sin selector en DB')

    if saved_selector:
      logger.info('[LinkedIn][extract] Paso 4: intentando click en selector guardado: %s', saved_selector)
      try:
        btn = page.locator(saved_selector).first
        btn_count = await btn.count()
        logger.info('[LinkedIn][extract] Paso 4: selector guardado count=%d', btn_count)
        if btn_count > 0:
          await btn.click(force=True)
          await asyncio.sleep(0.8)
          for sel in DESCRIPTION_SELECTORS:
            try:
              loc = page.locator(sel).first
              if await loc.count() == 0:
                continue
              html = await loc.inner_html(timeout=8_000)
              if html.strip():
                logger.info('[LinkedIn][extract] Paso 4: selector guardado funcionó: %s', saved_selector)
                return html, 'ok'
            except (PlaywrightTimeoutError, PlaywrightError):
              continue
          logger.warning('[LinkedIn][extract] Paso 4: click en selector guardado OK pero HTML sigue vacío')
        else:
          logger.warning('[LinkedIn][extract] Paso 4: selector guardado no existe en DOM: %s', saved_selector)
      except Exception as exc:  # noqa: BLE001
        logger.warning('[LinkedIn][extract] Paso 4: excepción con selector guardado: %s', exc)

    # --- LLM fallback: el razonador analiza el HTML completo para descubrir el selector ---
    logger.info('[LinkedIn][extract] Paso 5: CONSULTANDO LLM (%s) — obteniendo page.content()', self.extractor_html_model)
    try:
      from src.stealth.html_description_extractor import HTMLDescriptionExtractor
      page_html = await page.content()
      logger.info('[LinkedIn][extract] Paso 5: page.content() obtenido (len=%d) — enviando al LLM', len(page_html))
      llm_extractor = HTMLDescriptionExtractor(
        base_url=self.ollama_base_url,
        model=self.extractor_html_model,
      )
      # httpx.post es síncrono — ejecutar en thread para no bloquear el event loop de Playwright
      result = await asyncio.to_thread(llm_extractor.extract, page_html)
      logger.info('[LinkedIn][extract] Paso 5: LLM respondió | description_text_len=%d | expand_selector="%s"', len(result.get('description_text', '')), result.get('expand_selector', ''))

      if result.get('description_text'):
        logger.info('[LinkedIn][extract] Paso 5: LLM extrajo descripción directamente (len=%d)', len(result['description_text']))
        if result.get('expand_selector') and self._repo is not None:
          self._repo.kv_set('linkedin_expand_selector', result['expand_selector'])
          logger.info('[LinkedIn][extract] Paso 5: selector guardado en DB: %s', result['expand_selector'])
        return result['description_text'], 'ok_llm'

      if result.get('expand_selector'):
        selector = result['expand_selector']
        logger.info('[LinkedIn][extract] Paso 5: LLM devolvió selector de expansión: %s', selector)
        try:
          btn = page.locator(selector).first
          btn_count = await btn.count()
          logger.info('[LinkedIn][extract] Paso 5: selector LLM count=%d', btn_count)
          if btn_count > 0:
            await btn.click(force=True)
            await asyncio.sleep(0.8)
            for sel in DESCRIPTION_SELECTORS:
              try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                  continue
                html = await loc.inner_html(timeout=8_000)
                if html.strip():
                  logger.info('[LinkedIn][extract] Paso 5: click LLM exitoso con selector "%s" (html_len=%d)', sel, len(html))
                  if self._repo is not None:
                    self._repo.kv_set('linkedin_expand_selector', selector)
                    logger.info('[LinkedIn][extract] Paso 5: selector guardado en DB: %s', selector)
                  return html, 'ok_llm'
              except (PlaywrightTimeoutError, PlaywrightError):
                continue
            logger.warning('[LinkedIn][extract] Paso 5: click LLM OK pero HTML sigue vacío tras re-iteración')
          else:
            logger.warning('[LinkedIn][extract] Paso 5: selector LLM no encontrado en DOM: %s', selector)
        except Exception as exc:  # noqa: BLE001
          logger.warning('[LinkedIn][extract] Paso 5: excepción al usar selector LLM: %s', exc)
      else:
        logger.warning('[LinkedIn][extract] Paso 5: LLM no devolvió ni descripción ni selector — ambos vacíos')
    except Exception as exc:  # noqa: BLE001
      logger.warning('[LinkedIn][extract] Paso 5: LLM HTML extraction falló: %s', exc)

    logger.warning('[LinkedIn][extract] FALLO TOTAL — todos los pasos fallaron, retornando empty_description')
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
      'descripcion_md': 'Not available due to extraction error.',
      'scraped_at': datetime.now(UTC).isoformat(),
      'extraction_status': extraction_status,
      'error': error,
    }
