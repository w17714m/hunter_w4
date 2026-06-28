from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, Playwright, async_playwright
from playwright_stealth import Stealth


LINKEDIN_SEARCH_URL = 'https://www.linkedin.com/jobs/search/'
LINKEDIN_BASE_URL = 'https://www.linkedin.com'
DEFAULT_PROFILE_DIR = Path('data/playwright/linkedin-profile')
DEFAULT_USER_AGENT = (
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
  'AppleWebKit/537.36 (KHTML, like Gecko) '
  'Chrome/131.0.0.0 Safari/537.36'
)
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
  '.show-more-less-html__markup',
  '.description__text',
  '[class*="description"]',
)


@dataclass(frozen=True)
class JobPreview:
  title: str
  url: str


def build_search_url(keywords: str, location: str) -> str:
  return f'{LINKEDIN_SEARCH_URL}?{urlencode({"keywords": keywords, "location": location})}'


def normalize_url(url: str) -> str:
  absolute_url = urljoin(LINKEDIN_BASE_URL, url)
  parts = urlsplit(absolute_url)
  return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description='Verifica si Playwright + playwright-stealth puede abrir LinkedIn Jobs y extraer una oferta.'
  )
  parser.add_argument('--keywords', default='python developer')
  parser.add_argument('--location', default='Colombia')
  parser.add_argument('--limit', type=int, default=5)
  parser.add_argument('--headed', action='store_true')
  parser.add_argument('--profile-dir', default=str(DEFAULT_PROFILE_DIR))
  parser.add_argument('--timeout-ms', type=int, default=45_000)
  return parser.parse_args()


async def create_context(headed: bool, profile_dir: Path) -> tuple[Playwright, BrowserContext]:
  profile_dir.mkdir(parents=True, exist_ok=True)
  playwright = await async_playwright().start()
  try:
    context = await playwright.chromium.launch_persistent_context(
      user_data_dir=str(profile_dir),
      headless=not headed,
      user_agent=DEFAULT_USER_AGENT,
      locale='en-US',
      timezone_id='America/Bogota',
      viewport={'width': 1366, 'height': 768},
      args=[
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
      ],
    )
    context.set_default_timeout(45_000)
    return playwright, context
  except Exception:
    await playwright.stop()
    raise


async def apply_stealth(page: Page) -> None:
  await Stealth().apply_stealth_async(page)


async def is_blocked(page: Page) -> tuple[bool, str | None]:
  body_text = (await page.locator('body').inner_text(timeout=5_000)).lower()
  current_url = page.url.lower()
  for marker in BLOCK_MARKERS:
    if marker in current_url or marker in body_text:
      return True, marker
  return False, None


async def read_webdriver_flag(page: Page) -> str:
  value = await page.evaluate('String(navigator.webdriver)')
  return value


async def collect_job_previews(page: Page, limit: int) -> list[JobPreview]:
  links = page.locator('a[href*="/jobs/view/"]')
  count = await links.count()
  previews: list[JobPreview] = []
  seen: set[str] = set()

  for index in range(count):
    if len(previews) >= limit:
      break

    link = links.nth(index)
    href = await link.get_attribute('href')
    if not href:
      continue

    url = normalize_url(href)
    if url in seen:
      continue

    title = ' '.join((await link.inner_text()).split())
    if not title:
      title = 'Oferta sin titulo visible'

    seen.add(url)
    previews.append(JobPreview(title=title, url=url))

  return previews


async def extract_description(page: Page) -> str:
  for selector in DESCRIPTION_SELECTORS:
    locator = page.locator(selector).first
    if await locator.count() == 0:
      continue
    text = ' '.join((await locator.inner_text(timeout=8_000)).split())
    if len(text) >= 200:
      return text

  body_text = ' '.join((await page.locator('body').inner_text(timeout=8_000)).split())
  return body_text


def print_previews(previews: Sequence[JobPreview]) -> None:
  print(f'Ofertas detectadas: {len(previews)}')
  for index, preview in enumerate(previews, start=1):
    print(f'{index}. {preview.title}')
    print(f'   {preview.url}')


async def run() -> int:
  args = parse_args()
  profile_dir = Path(args.profile_dir)
  try:
    playwright, context = await create_context(args.headed, profile_dir)
  except PlaywrightError as error:
    message = str(error)
    if 'Executable doesn' in message or 'playwright install' in message:
      print('Resultado: PLAYWRIGHT_BROWSER_MISSING')
      print('Instala Chromium con: uv run playwright install chromium')
      return 10
    raise

  page = await context.new_page()

  try:
    await apply_stealth(page)
    search_url = build_search_url(args.keywords, args.location)
    response = await page.goto(search_url, wait_until='domcontentloaded', timeout=args.timeout_ms)
    await page.wait_for_timeout(3_000)

    status = response.status if response else None
    blocked, marker = await is_blocked(page)
    webdriver_flag = await read_webdriver_flag(page)

    print(f'Perfil persistente: {profile_dir.resolve()}')
    print(f'Busqueda: {search_url}')
    print(f'HTTP status: {status}')
    print(f'URL final: {page.url}')
    print(f'navigator.webdriver: {webdriver_flag}')

    if blocked:
      print(f'Resultado: BLOQUEADO o login requerido ({marker})')
      return 2

    previews = await collect_job_previews(page, args.limit)
    print_previews(previews)

    if not previews:
      print('Resultado: NO VERIFICADO, no se encontraron enlaces de ofertas.')
      return 3

    first_job = previews[0]
    await page.goto(first_job.url, wait_until='domcontentloaded', timeout=args.timeout_ms)
    await page.wait_for_timeout(3_000)

    detail_blocked, detail_marker = await is_blocked(page)
    if detail_blocked:
      print(f'Resultado: BUSQUEDA OK, detalle bloqueado o requiere login ({detail_marker})')
      return 4

    description = await extract_description(page)
    print(f'Detalle probado: {first_job.url}')
    print(f'Caracteres extraidos: {len(description)}')
    print(f'Muestra: {description[:500]}')

    if len(description) < 500:
      print('Resultado: PARCIAL, abrio LinkedIn pero no extrajo una descripcion suficiente.')
      return 5

    print('Resultado: OK, LinkedIn abrio y se pudo extraer texto de una oferta.')
    return 0
  finally:
    await context.close()
    await playwright.stop()


if __name__ == '__main__':
  raise SystemExit(asyncio.run(run()))