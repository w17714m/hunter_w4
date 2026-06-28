from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from playwright_stealth import Stealth

from src.core.normalize import canonicalize_url
from src.core.url_seen_filter import URLSeenFilter
from src.stealth.human_delays import between_requests_delay
from src.stealth.playwright_stealth_extras import random_extra_headers, random_scroll, random_user_agent, random_viewport
from src.stealth.warp_rotator import WarpRotator

logger = logging.getLogger(__name__)

_ELEMPLEO_BASE_URL_DEFAULT = 'https://www.elempleo.com'

_BLOCK_STATUSES = (403,)


class ElempleoParser:
  def extract_links(self, html: str, base_url: str = _ELEMPLEO_BASE_URL_DEFAULT) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.select('a[href]'):
      href = (anchor.get('href') or '').strip()
      if not href:
        continue
      full_url = urljoin(base_url, href)
      if '/ofertas-trabajo/' not in full_url:
        continue
      canonical = canonicalize_url(full_url)
      if canonical in seen:
        continue
      seen.add(canonical)
      links.append(canonical)

    return links

  def parse_offer_page(self, html: str, offer_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, 'html.parser')
    titulo = self._extract_text(
      soup,
      [
        'h1',
        '[data-testid="job-title"]',
        'meta[property="og:title"]',
      ],
      default='Sin titulo',
    )
    empresa = self._extract_text(
      soup,
      [
        '.company-name',
        '[data-testid="company-name"]',
        'meta[property="og:site_name"]',
      ],
    )
    ubicacion = self._extract_text(
      soup,
      [
        '.job-location',
        '[data-testid="job-location"]',
      ],
    )
    fecha_publicacion = self._extract_text(
      soup,
      [
        'time[datetime]',
        '.job-date',
      ],
    )

    descripcion_md = self.html_to_markdown(html)
    return {
      'url': canonicalize_url(offer_url),
      'titulo': titulo,
      'empresa': empresa,
      'ubicacion': ubicacion,
      'fecha_publicacion': fecha_publicacion,
      'descripcion_md': descripcion_md,
    }

  @staticmethod
  def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag_name in ['script', 'style', 'nav', 'header', 'footer', 'aside']:
      for node in soup.find_all(tag_name):
        node.decompose()

    return md(
      str(soup),
      strip=['script', 'style', 'nav', 'header', 'footer', 'aside'],
      heading_style='ATX',
    ).strip()

  @staticmethod
  def _extract_text(soup: BeautifulSoup, selectors: list[str], default: str | None = None) -> str | None:
    for selector in selectors:
      node = soup.select_one(selector)
      if node is None:
        continue
      if node.name == 'meta':
        content = (node.get('content') or '').strip()
        if content:
          return content
        continue
      if node.name == 'time':
        dt = (node.get('datetime') or '').strip()
        if dt:
          return dt
      text = node.get_text(' ', strip=True)
      if text:
        return text
    return default


class ElempleoCollector:
  def __init__(
    self,
    parser: ElempleoParser | None = None,
    timeout_ms: int = 45_000,
    max_offers_per_search: int = 20,
    headless: bool = True,
    warp_rotator: WarpRotator | None = None,
    max_ip_rotations: int = 2,
    url_filter: URLSeenFilter | None = None,
    base_url: str = _ELEMPLEO_BASE_URL_DEFAULT,
  ) -> None:
    self.parser = parser or ElempleoParser()
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

  def build_search_urls(self, busquedas_elempleo: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for item in busquedas_elempleo:
      if url_directa := (item.get('url_directa') or '').strip():
        urls.append(url_directa)
        continue
      urls.append(self._build_structured_url(item))
    return urls

  @staticmethod
  def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r'[áàäâ]', 'a', text)
    text = re.sub(r'[éèëê]', 'e', text)
    text = re.sub(r'[íìïî]', 'i', text)
    text = re.sub(r'[óòöô]', 'o', text)
    text = re.sub(r'[úùüû]', 'u', text)
    text = re.sub(r'ñ', 'n', text)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    return text.strip('-')

  def _build_structured_url(self, item: dict[str, Any]) -> str:
    base = f'{self.base_url}/co/ofertas-empleo'
    cargo_raw = (item.get('cargo') or '').strip()
    modalidad = (item.get('modalidad') or '').strip()
    salarios: list[str] = item.get('salarios') or []
    tipos_contrato: list[str] = item.get('tipos_contrato') or []
    fecha_publicacion = (item.get('fecha_publicacion') or '').strip()

    slug_parts = ['trabajo', ElempleoCollector._slugify(cargo_raw)]
    if modalidad:
      slug_parts += ['modalidad', modalidad]
    slug = '-'.join(part for part in slug_parts if part)

    params: list[str] = []
    if salarios:
      params.append('Salaries=' + ':'.join(salarios))
    if tipos_contrato:
      params.append('ContractTypes=' + ':'.join(tipos_contrato))
    if fecha_publicacion:
      params.append(f'PublishDate={fecha_publicacion}')

    url = f'{base}/{slug}'
    if params:
      url += '?' + '&'.join(params)
    return url

  async def collect(self, busquedas_elempleo: list[dict[str, str]]) -> list[dict[str, Any]]:
    search_urls = self.build_search_urls(busquedas_elempleo)
    if not search_urls:
      return []

    results: list[dict[str, Any]] = []
    playwright = await async_playwright().start()
    try:
      browser = await playwright.chromium.launch(headless=self.headless)
      context = await browser.new_context(
        user_agent=random_user_agent(),
        viewport=random_viewport(),
        extra_http_headers=random_extra_headers(),
      )
      page = await context.new_page()
      page.set_default_timeout(self.timeout_ms)
      await Stealth().apply_stealth_async(page)

      for search_url in search_urls:
        try:
          search_response = await page.goto(search_url, wait_until='domcontentloaded')

          if search_response is not None and search_response.status in _BLOCK_STATUSES:
            recovered = False
            for _ in range(self.max_ip_rotations):
              if not await self._try_rotate():
                break
              await between_requests_delay()
              search_response = await page.goto(search_url, wait_until='domcontentloaded')
              if search_response is None or search_response.status not in _BLOCK_STATUSES:
                recovered = True
                break
            if not recovered:
              results.append(self._build_error_result(search_url, 'blocked_403', 'Search blocked (403)'))
              continue

          search_html = await page.content()
          offer_links = self.parser.extract_links(search_html, base_url=self.base_url)
          if self.url_filter:
            already_seen = self.url_filter.bulk_seen('elempleo', offer_links)
            if already_seen:
              logger.info('[elempleo] %d/%d URLs ya procesadas, omitidas', len(already_seen), len(offer_links))
            offer_links = [u for u in offer_links if u not in already_seen]

          for offer_url in offer_links[: self.max_offers_per_search]:
            try:
              offer_response = await page.goto(offer_url, wait_until='domcontentloaded')

              if offer_response is not None and offer_response.status in _BLOCK_STATUSES:
                recovered = False
                for _ in range(self.max_ip_rotations):
                  if not await self._try_rotate():
                    break
                  await between_requests_delay()
                  offer_response = await page.goto(offer_url, wait_until='domcontentloaded')
                  if offer_response is None or offer_response.status not in _BLOCK_STATUSES:
                    recovered = True
                    break
                if not recovered:
                  results.append(self._build_error_result(offer_url, 'blocked_403', 'Offer blocked (403)'))
                  continue

              await random_scroll(page)
              offer_html = await page.content()
              parsed = self.parser.parse_offer_page(offer_html, offer_url)
              results.append(
                {
                  **parsed,
                  'fuente': 'elempleo',
                  'scraped_at': datetime.now(UTC).isoformat(),
                  'extraction_status': 'ok',
                },
              )
            except (PlaywrightTimeoutError, PlaywrightError) as error:
              results.append(self._build_error_result(offer_url, 'fetch_failed', str(error)))
        except (PlaywrightTimeoutError, PlaywrightError) as error:
          results.append(self._build_error_result(search_url, 'fetch_failed', str(error)))

      await context.close()
      await browser.close()
      return results
    except PlaywrightError as error:
      return [self._build_error_result('', 'playwright_error', str(error))]
    finally:
      await playwright.stop()

  @staticmethod
  def _build_error_result(url: str, extraction_status: str, error: str) -> dict[str, Any]:
    return {
      'url': url,
      'fuente': 'elempleo',
      'titulo': None,
      'empresa': None,
      'ubicacion': None,
      'descripcion_md': 'No disponible por error de extraccion.',
      'scraped_at': datetime.now(UTC).isoformat(),
      'extraction_status': extraction_status,
      'error': error,
    }
