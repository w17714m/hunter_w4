from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Error as PlaywrightError, async_playwright
from playwright_stealth import Stealth


DEFAULT_PROFILE_DIR = Path('data/playwright/linkedin-profile')
DEFAULT_START_URL = 'https://www.linkedin.com/login'
DEFAULT_USER_AGENT = (
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
  'AppleWebKit/537.36 (KHTML, like Gecko) '
  'Chrome/131.0.0.0 Safari/537.36'
)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description='Abre LinkedIn con un perfil persistente de Playwright para iniciar sesion y conservarla.'
  )
  parser.add_argument('--profile-dir', default=str(DEFAULT_PROFILE_DIR))
  parser.add_argument('--url', default=DEFAULT_START_URL)
  parser.add_argument('--timeout-ms', type=int, default=60_000)
  return parser.parse_args()


async def wait_for_user() -> None:
  await asyncio.to_thread(input, 'Inicia sesion en LinkedIn y presiona Enter aqui para cerrar y guardar la sesion...')


async def run() -> int:
  args = parse_args()
  profile_dir = Path(args.profile_dir)
  profile_dir.mkdir(parents=True, exist_ok=True)

  playwright = await async_playwright().start()
  try:
    context = await playwright.chromium.launch_persistent_context(
      user_data_dir=str(profile_dir),
      headless=False,
      user_agent=DEFAULT_USER_AGENT,
      locale='en-US',
      timezone_id='America/Bogota',
      viewport={'width': 1366, 'height': 768},
      args=[
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
      ],
    )
  except PlaywrightError as error:
    await playwright.stop()
    message = str(error)
    if 'Executable doesn' in message or 'playwright install' in message:
      print('Resultado: PLAYWRIGHT_BROWSER_MISSING')
      print('Instala Chromium con: uv run playwright install chromium')
      return 10
    raise

  try:
    context.set_default_timeout(args.timeout_ms)
    page = context.pages[0] if context.pages else await context.new_page()
    await Stealth().apply_stealth_async(page)
    await page.goto(args.url, wait_until='domcontentloaded', timeout=args.timeout_ms)
    print(f'Perfil persistente: {profile_dir.resolve()}')
    print(f'URL abierta: {page.url}')
    await wait_for_user()
    return 0
  finally:
    await context.close()
    await playwright.stop()


if __name__ == '__main__':
  raise SystemExit(asyncio.run(run()))
