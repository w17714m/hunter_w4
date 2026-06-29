from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from markdownify import markdownify as md
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from playwright_stealth import Stealth

from src.core.url_seen_filter import URLSeenFilter
from src.stealth.human_delays import between_requests_delay, page_load_delay
from src.stealth.playwright_stealth_extras import random_extra_headers, random_user_agent, random_scroll, random_viewport
from src.stealth.warp_rotator import WarpRotator

logger = logging.getLogger(__name__)

_COMPUTRABAJO_BASE_URL_DEFAULT = 'https://co.computrabajo.com'
COMPUTRABAJO_BASE_URL = _COMPUTRABAJO_BASE_URL_DEFAULT  # overridden at runtime via cfg.fuentes
MAX_PAGES = 5
_BLOCK_STATUSES = (403, 429, 999)

# ---------------------------------------------------------------------------
# Selectors — search results listing
# ---------------------------------------------------------------------------
# Grid: div#offersGridOfferContainer > article.box_offer[data-id] > h2 > a.js-o-link
OFFER_GRID_SELECTOR = '#offersGridOfferContainer'
OFFER_ARTICLE_SELECTOR = 'article.box_offer[data-id]'
OFFER_LINK_IN_ARTICLE = 'a.js-o-link'
OFFER_LINK_FALLBACK = 'a[href*="/ofertas-de-trabajo/oferta-de-trabajo-de-"]'

# ---------------------------------------------------------------------------
# Selectors — offer detail page (real DOM 2025)
# ---------------------------------------------------------------------------
# Main offer container: div[description-offer] (attribute, not class)
# Inside: div[div-link="oferta"] holds all job vacancy content.
#
# Internal structure of div[div-link="oferta"]:
#   h3.fwB.fs18.mb20           → "Descripción de la oferta" (heading)
#   div.mbB > span.tag.base    → metadata tags (salary, contract, schedule, modality)
#   p.mbB                      → main description text (with <br>)
#   ul.disc.mbB > li           → requirements list
#   p.fc_aux.fs13.mbB.mtB      → keywords
#
# Company container: div[div-link="empresa"] > p.fs18.mb20.fwB
OFFER_DETAIL_CONTAINER = '[description-offer]'
OFFER_CONTENT_SECTION = '[div-link="oferta"]'

# Metadata selectors in the listing (article.box_offer)
# Job title: h2 > a.js-o-link (in the listing)
# Company: p.dFlex.vm_fx > a[offer-grid-article-company-url]
# Location: p.fs16.fc_base.mt5 > span.mr10

# Selectors for extraction on the detail page
TITLE_SELECTORS = [
  'h1',                              # generic fallback
]
COMPANY_SELECTORS = [
  f'[div-link="empresa"] p.fs18.mb20.fwB',   # "Acerca de EMPRESA S.A."
  f'[div-link="empresa"] .fwB',
]
LOCATION_SELECTORS = [
  'p.fs16.fc_base.mt5 span.mr10',   # en el panel lateral del listado
  'p.fs16.mb5 span.mr10',
]


def _slugify(text: str) -> str:
  text = text.strip().lower()
  for src, dst in [('á','a'),('à','a'),('ä','a'),('â','a'),
                   ('é','e'),('è','e'),('ë','e'),('ê','e'),
                   ('í','i'),('ì','i'),('ï','i'),('î','i'),
                   ('ó','o'),('ò','o'),('ö','o'),('ô','o'),
                   ('ú','u'),('ù','u'),('ü','u'),('û','u'),('ñ','n')]:
    text = text.replace(src, dst)
  text = re.sub(r'[^a-z0-9\s-]', '', text)
  text = re.sub(r'[\s]+', '-', text)
  return text.strip('-')


def normalize_computrabajo_url(url: str) -> str:
  absolute = urljoin(COMPUTRABAJO_BASE_URL, url)
  parts = urlsplit(absolute)
  return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def build_computrabajo_search_url(item: dict[str, Any], base_url: str = _COMPUTRABAJO_BASE_URL_DEFAULT) -> str:
  from src.config.schemas import (
    COMPUTRABAJO_CONT_MAP,
    COMPUTRABAJO_JORNADA_MAP,
    COMPUTRABAJO_LUGAR_MAP,
    COMPUTRABAJO_PUBDATE_MAP,
    COMPUTRABAJO_SAL_MAP,
  )

  cargo_slug = _slugify((item.get('cargo') or '').strip())

  # Path segments: cargo + optional jornada + optional lugar
  path_parts = [f'empleos-de-{cargo_slug}']

  if jornada := (item.get('jornada') or '').strip():
    if slug := COMPUTRABAJO_JORNADA_MAP.get(jornada):
      path_parts.append(f'jornada-{slug}')

  if lugar := (item.get('lugar_trabajo') or '').strip():
    if slug := COMPUTRABAJO_LUGAR_MAP.get(lugar):
      path_parts.append(f'en-{slug}')

  path = '-'.join(path_parts)

  # Query params: cont, sal, pubdate
  params: dict[str, Any] = {}

  if tipo := (item.get('tipo_contrato') or '').strip():
    if code := COMPUTRABAJO_CONT_MAP.get(tipo):
      params['cont'] = code

  if sal := (item.get('salario_minimo') or '').strip():
    if code := COMPUTRABAJO_SAL_MAP.get(sal):
      params['sal'] = code

  if pub := (item.get('fecha_publicacion') or '').strip():
    if code := COMPUTRABAJO_PUBDATE_MAP.get(pub):
      params['pubdate'] = code

  base = f'{base_url}/{path}'
  return f'{base}?{urlencode(params)}' if params else base


class ComputrabajoParser:
  def extract_offer_links(self, html: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    seen: set[str] = set()
    links: list[str] = []

    # Strategy 1: real articles in the offer grid
    # Structure: article.box_offer[data-id] > h2 > a.js-o-link
    grid = soup.select_one(OFFER_GRID_SELECTOR)
    search_root = grid if grid else soup

    for article in search_root.select(OFFER_ARTICLE_SELECTOR):
      anchor = article.select_one(OFFER_LINK_IN_ARTICLE)
      if anchor is None:
        continue
      href = (anchor.get('href') or '').strip()
      if not href:
        continue
      url = normalize_computrabajo_url(href)
      if url in seen:
        continue
      seen.add(url)
      links.append(url)

    # Estrategia 2: fallback — cualquier link con el path de oferta
    if not links:
      for anchor in soup.select(OFFER_LINK_FALLBACK):
        href = (anchor.get('href') or '').strip()
        if not href:
          continue
        url = normalize_computrabajo_url(href)
        if url in seen:
          continue
        seen.add(url)
        links.append(url)

    return links

  def parse_offer_detail(self, html: str) -> dict[str, str | None]:
    """Extract title, company, location and descripcion_md from offer detail page HTML.

    Real DOM structure (co.computrabajo.com 2025):
      [description-offer] > [div-link="oferta"]
        span.tag.base        → salary, contract, schedule, modality
        p.mbB                → main text (with <br>)
        ul.disc.mbB > li     → requirements
      [description-offer] > [div-link="empresa"]
        p.fs18.mb20.fwB      → "Acerca de EMPRESA" (contains the company name)
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')

    # ---- Main container ----
    container = soup.select_one(OFFER_DETAIL_CONTAINER) or soup
    content = container.select_one(OFFER_CONTENT_SECTION) or container

    # ---- Title: h1 or the first real h3 in the content block ----
    titulo: str | None = None
    h1 = soup.select_one('h1')
    if h1:
      titulo = h1.get_text(' ', strip=True) or None

    # ---- Company: from div[div-link="empresa"] ----
    empresa: str | None = None
    empresa_section = container.select_one('[div-link="empresa"]')
    if empresa_section:
      empresa_p = empresa_section.select_one('p.fs18.mb20.fwB, .fwB')
      if empresa_p:
        raw = empresa_p.get_text(' ', strip=True)
        # Strip "Acerca de " prefix if present
        empresa = re.sub(r'^Acerca de\s+', '', raw, flags=re.IGNORECASE).strip() or None

    # ---- Location: span.mr10 inside the listing article or page ----
    ubicacion: str | None = None
    for sel in ('p.fs16.fc_base.mt5 span.mr10', 'p.fs16.mb5 span.mr10', 'p.fs16 span.mr10'):
      node = soup.select_one(sel)
      if node:
        text = node.get_text(' ', strip=True)
        if text:
          ubicacion = text
          break

    # ---- Description → Markdown ----
    descripcion_md = self._build_description_markdown(content)

    return {
      'titulo': titulo,
      'empresa': empresa,
      'ubicacion': ubicacion,
      'descripcion_md': descripcion_md,
    }

  def _build_description_markdown(self, content: Any) -> str:
    """Build clean Markdown from the offer content block.

    Sections extracted in order:
      1. Metadata tags (salary, contract, schedule, modality)
      2. Main description text (p.mbB)
      3. Requirements (ul.disc.mbB)
      4. Keywords (p.fc_aux.fs13.mbB.mtB)
    """
    from bs4 import BeautifulSoup, Tag

    parts: list[str] = []

    # 1. Metadata tags — span.tag.base
    tag_nodes = content.select('div.mbB > span.tag.base')
    if tag_nodes:
      tags_text = ' | '.join(t.get_text(' ', strip=True) for t in tag_nodes if t.get_text(strip=True))
      if tags_text:
        parts.append(tags_text)
        parts.append('')

    # 2. Main description text — p.mbB (first long paragraph)
    for p in content.select('p.mbB'):
      raw_html = str(p)
      text = md(raw_html, heading_style='ATX').strip()
      if len(text) > 20:
        parts.append(text)
        parts.append('')
        break

    # 3. Requerimientos — ul.disc.mbB
    req_list = content.select_one('ul.disc.mbB')
    if req_list:
      parts.append('## Requerimientos')
      for li in req_list.select('li'):
        item_text = li.get_text(' ', strip=True)
        if item_text:
          parts.append(f'- {item_text}')
      parts.append('')

    # 4. Palabras clave — p.fc_aux.fs13.mbB.mtB
    kw_node = content.select_one('p.fc_aux.fs13')
    if kw_node:
      kw_text = kw_node.get_text(' ', strip=True)
      if kw_text and 'palabras clave' in kw_text.lower():
        parts.append(f'*{kw_text}*')

    return '\n'.join(parts).strip()

  def description_html_to_markdown(self, html: str) -> str:
    """Convert arbitrary HTML to Markdown (used as fallback)."""
    return md(html, heading_style='ATX').strip()

  @staticmethod
  def extract_text_from_html(html: str, selectors: list[str]) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    for selector in selectors:
      node = soup.select_one(selector)
      if node is None:
        continue
      text = node.get_text(' ', strip=True)
      if text:
        return text
    return None


class ComputrabajoCollector:
  def __init__(
    self,
    parser: ComputrabajoParser | None = None,
    timeout_ms: int = 45_000,
    max_offers_per_search: int = 20,
    headless: bool = True,
    warp_rotator: WarpRotator | None = None,
    max_ip_rotations: int = 2,
    url_filter: URLSeenFilter | None = None,
    base_url: str = _COMPUTRABAJO_BASE_URL_DEFAULT,
  ) -> None:
    self.parser = parser or ComputrabajoParser()
    self.timeout_ms = timeout_ms
    self.max_offers_per_search = max_offers_per_search
    self.headless = headless
    self.warp_rotator = warp_rotator
    self.url_filter = url_filter
    self.max_ip_rotations = max_ip_rotations
    self.base_url = base_url

  async def _try_rotate(self) -> bool:
    """Attempt an IP rotation if a rotator is configured."""
    if self.warp_rotator is None:
      return False
    return await self.warp_rotator.rotate()

  def build_search_urls(self, busquedas: list[dict[str, Any]]) -> list[str]:
    return [build_computrabajo_search_url(item, base_url=self.base_url) for item in busquedas]

  async def collect(self, busquedas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    search_urls = self.build_search_urls(busquedas)
    if not search_urls:
      return []

    results: list[dict[str, Any]] = []
    playwright = await async_playwright().start()
    try:
      browser = await playwright.chromium.launch(headless=self.headless)
    except PlaywrightError as error:
      await playwright.stop()
      message = str(error)
      if 'Executable doesn' in message or 'playwright install' in message:
        return [self._build_error_result('', 'blocked', 'PLAYWRIGHT_BROWSER_MISSING')]
      return [self._build_error_result('', 'blocked', message)]

    try:
      context = await browser.new_context(
        user_agent=random_user_agent(),
        locale='es-CO',
        timezone_id='America/Bogota',
        viewport=random_viewport(),
        extra_http_headers=random_extra_headers(),
      )
      context.set_default_timeout(self.timeout_ms)
      page = await context.new_page()
      await Stealth().apply_stealth_async(page)

      for search_url in search_urls:
        try:
          offer_links = await self._paginate_and_collect(page, search_url)
          if self.url_filter:
            already_seen = self.url_filter.bulk_seen('computrabajo', offer_links)
            if already_seen:
              logger.info('[computrabajo] %d/%d URLs ya procesadas, omitidas', len(already_seen), len(offer_links))
            offer_links = [u for u in offer_links if u not in already_seen]
          for offer_url in offer_links[: self.max_offers_per_search]:
            result = await self._fetch_offer(page, offer_url)
            results.append(result)
        except (PlaywrightTimeoutError, PlaywrightError) as error:
          results.append(self._build_error_result(search_url, 'blocked', str(error)))

      await context.close()
      await browser.close()
      return results
    finally:
      await playwright.stop()

  async def _paginate_and_collect(self, page: Any, search_url: str) -> list[str]:
    all_links: list[str] = []
    seen: set[str] = set()

    for page_num in range(1, MAX_PAGES + 1):
      paginated_url = f'{search_url}{"&" if "?" in search_url else "?"}p={page_num}' if page_num > 1 else search_url
      try:
        response = await page.goto(paginated_url, wait_until='domcontentloaded')

        if response is not None and response.status in _BLOCK_STATUSES:
          # Attempt IP rotation and retry before giving up on this pagination
          recovered = False
          for _ in range(self.max_ip_rotations):
            if not await self._try_rotate():
              break
            await between_requests_delay()
            response = await page.goto(paginated_url, wait_until='domcontentloaded')
            if response is None or response.status not in _BLOCK_STATUSES:
              recovered = True
              break
          if not recovered:
            break

        html = await page.content()
        page_links = self.parser.extract_offer_links(html)
        if not page_links:
          break

        for url in page_links:
          if url not in seen:
            seen.add(url)
            all_links.append(url)

        if len(all_links) >= self.max_offers_per_search:
          break

        await page_load_delay()

      except (PlaywrightTimeoutError, PlaywrightError):
        break

    return all_links

  async def _fetch_offer(self, page: Any, offer_url: str) -> dict[str, Any]:
    try:
      response = await page.goto(offer_url, wait_until='domcontentloaded')

      if response is not None and response.status in _BLOCK_STATUSES:
        # Attempt IP rotation and retry before marking as blocked
        recovered = False
        for _ in range(self.max_ip_rotations):
          if not await self._try_rotate():
            break
          await between_requests_delay()
          response = await page.goto(offer_url, wait_until='domcontentloaded')
          if response is None or response.status not in _BLOCK_STATUSES:
            recovered = True
            break
        if not recovered:
          return self._build_error_result(offer_url, 'blocked', f'HTTP {response.status if response else "unknown"}')

      # Wait for the offer content anchor to appear in the DOM
      anchor = f'{OFFER_DETAIL_CONTAINER} {OFFER_CONTENT_SECTION} p.mbB'
      try:
        await page.wait_for_selector(anchor, timeout=15_000)
      except (PlaywrightTimeoutError, PlaywrightError):
        try:
          await page.wait_for_selector(OFFER_DETAIL_CONTAINER, timeout=5_000)
        except (PlaywrightTimeoutError, PlaywrightError):
          pass

      await random_scroll(page)
      full_html = await page.content()
      parsed = self.parser.parse_offer_detail(full_html)

      if not parsed['descripcion_md']:
        return self._build_error_result(offer_url, 'empty_description', 'Empty markdown after extraction')

      return {
        'url': normalize_computrabajo_url(offer_url),
        'titulo': parsed['titulo'] or 'Sin titulo',
        'empresa': parsed['empresa'],
        'ubicacion': parsed['ubicacion'],
        'descripcion_md': parsed['descripcion_md'],
        'fuente': 'computrabajo',
        'scraped_at': datetime.now(UTC).isoformat(),
        'posted_date': datetime.now(UTC).strftime('%Y-%m-%d'),
        'extraction_status': 'ok',
      }
    except (PlaywrightTimeoutError, PlaywrightError) as error:
      return self._build_error_result(offer_url, 'blocked', str(error))

  @staticmethod
  def _build_error_result(url: str, extraction_status: str, error: str) -> dict[str, Any]:
    return {
      'url': url,
      'fuente': 'computrabajo',
      'titulo': None,
      'empresa': None,
      'ubicacion': None,
      'descripcion_md': 'No disponible por error de extraccion.',
      'scraped_at': datetime.now(UTC).isoformat(),
      'posted_date': datetime.now(UTC).strftime('%Y-%m-%d'),
      'extraction_status': extraction_status,
      'error': error,
    }
