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


async def expand_description(page: Any) -> bool:
    """Click the LinkedIn 'show more' button to reveal the full job description.

    The outer <button data-testid="expandable-text-button"> has
    `pointer-events: none` set inline, so a normal click is rejected by
    Playwright.  The first child <span> carries `pointer-events: auto` and is
    the real hit target.  force=True bypasses Playwright's pointer-events
    check and dispatches the event directly to that span.
    """
    try:
        btn = page.locator('[data-testid="expandable-text-button"]').first
        if await btn.count() == 0:
            return False
        span = btn.locator('span').first
        if await span.count() == 0:
            return False
        await span.click(force=True)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        return True
    except Exception:  # noqa: BLE001
        return False  # best-effort; never block extraction


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
