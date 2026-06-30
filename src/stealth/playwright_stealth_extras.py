from __future__ import annotations

import asyncio
import random
from typing import Any, TypedDict


class ViewportSize(TypedDict):
    width: int
    height: int


_REALISTIC_VIEWPORTS: list[ViewportSize] = [
    {'width': 1920, 'height': 1080},
    {'width': 1366, 'height': 768},
    {'width': 1536, 'height': 864},
    {'width': 1440, 'height': 900},
    {'width': 1280, 'height': 720},
    {'width': 1600, 'height': 900},
]

_REAL_USER_AGENTS: list[str] = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0',
]

_ACCEPT_LANGUAGE_VARIANTS: list[str] = [
    'es-CO,es;q=0.9,en-US;q=0.8,en;q=0.7',
    'es-CO,es;q=0.9,en;q=0.8',
    'en-US,en;q=0.9,es;q=0.8',
    'es,en-US;q=0.9,en;q=0.8',
]


def random_viewport() -> ViewportSize:
    """Return a randomly chosen realistic desktop viewport."""
    return random.choice(_REALISTIC_VIEWPORTS)


def random_user_agent() -> str:
    """Return a randomly chosen real browser user-agent string."""
    return random.choice(_REAL_USER_AGENTS)


def random_extra_headers() -> dict[str, str]:
    """Return extra HTTP headers that vary between sessions."""
    return {
        'Accept-Language': random.choice(_ACCEPT_LANGUAGE_VARIANTS),
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
    }


async def random_scroll(page: Any) -> None:
    """Scroll down the page in random steps to simulate human reading, then reset to top."""
    try:
        total_height: int = await page.evaluate('document.body.scrollHeight')
        steps = random.randint(2, 5)
        for _ in range(steps):
            scroll_by = random.randint(200, max(250, total_height // 4))
            await page.evaluate(f'window.scrollBy(0, {scroll_by})')
            await asyncio.sleep(random.uniform(0.2, 0.6))
        await page.evaluate('window.scrollTo(0, 0)')
    except Exception:  # noqa: BLE001
        pass  # scroll is best-effort; never block content extraction


_EXPAND_SELECTORS = (
    # data-testid variants (LinkedIn rotates these)
    '[data-testid="expandable-text-button"]',
    '[data-testid="show-more-btn"]',
    '[data-testid="jobs-description-expandable-button"]',
    # aria-label variants (ES / EN)
    '[aria-label="ver más"]',
    '[aria-label="Ver más"]',
    '[aria-label="show more"]',
    '[aria-label="Show more"]',
    '[aria-label="see more"]',
    # data-control-name (classic DOM)
    '[data-control-name="show_more"]',
    '[data-control-name="jobs_description_web_details"]',
    # Visible text — Playwright :has-text() matches partial content
    'button:has-text("Ver más")',
    'button:has-text("ver más")',
    'button:has-text("Show more")',
    'button:has-text("show more")',
    'button:has-text("See more")',
    'button:has-text("...more")',
    'button:has-text("…more")',
    'span:has-text("Ver más")',
    'span:has-text("Show more")',
)


async def expand_description(page: Any) -> bool:
    """Click the LinkedIn 'show more' button to reveal the full job description.

    Tries multiple selectors in order because LinkedIn rotates data-testid and
    other attributes. For each candidate, first tries clicking the element directly
    with force=True, then tries its first child <span> (LinkedIn sometimes sets
    pointer-events:none on the outer button so the span is the real hit target).
    Returns True on the first successful click, False if nothing matched.
    """
    for selector in _EXPAND_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() == 0:
                continue
            # Try direct click first
            try:
                await btn.click(force=True)
                await asyncio.sleep(random.uniform(0.4, 0.8))
                return True
            except Exception:  # noqa: BLE001
                pass
            # Fallback: click the first child span (pointer-events workaround)
            span = btn.locator('span').first
            if await span.count() > 0:
                await span.click(force=True)
                await asyncio.sleep(random.uniform(0.4, 0.8))
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def human_mouse_move_to(page: Any, locator: Any) -> None:
    """Move the mouse gradually toward a locator before clicking."""
    try:
        box = await locator.bounding_box()
        if box is None:
            return
        target_x = box['x'] + box['width'] / 2 + random.uniform(-5, 5)
        target_y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
        # Move from a nearby offset first, then approach the target
        await page.mouse.move(
            target_x + random.uniform(-60, 60),
            target_y + random.uniform(-40, 40),
        )
        await asyncio.sleep(random.uniform(0.08, 0.2))
        await page.mouse.move(target_x, target_y)
    except Exception:  # noqa: BLE001
        pass  # mouse movement is best-effort
