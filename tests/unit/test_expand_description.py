from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.stealth.playwright_stealth_extras import _EXPAND_SELECTORS, expand_description


def _page_all_empty() -> MagicMock:
    """Page where every selector returns count=0 — simulates no expand button."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    loc.first = loc
    page = MagicMock()
    page.locator = MagicMock(return_value=loc)
    return page


def _page_first_selector_present(span_count: int = 1, click_raises: bool = False) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Page where only the first _EXPAND_SELECTORS entry returns count=1."""
    span_loc = MagicMock()
    span_loc.count = AsyncMock(return_value=span_count)
    if click_raises:
        span_loc.click = AsyncMock(side_effect=Exception('click failed'))
    else:
        span_loc.click = AsyncMock()
    span_loc.first = span_loc

    btn_loc = MagicMock()
    btn_loc.count = AsyncMock(return_value=1)
    btn_loc.click = AsyncMock()
    btn_loc.locator = MagicMock(return_value=span_loc)
    btn_loc.first = btn_loc

    empty_loc = MagicMock()
    empty_loc.count = AsyncMock(return_value=0)
    empty_loc.first = empty_loc

    first_selector = _EXPAND_SELECTORS[0]

    def locator_side(selector: str) -> MagicMock:
        return btn_loc if selector == first_selector else empty_loc

    page = MagicMock()
    page.locator = MagicMock(side_effect=locator_side)
    return page, btn_loc, span_loc


# ---------------------------------------------------------------------------
# No button present in any selector
# ---------------------------------------------------------------------------

async def test_returns_false_when_no_button():
    page = _page_all_empty()
    result = await expand_description(page)
    assert result is False


# ---------------------------------------------------------------------------
# Button present, direct click succeeds (happy path)
# ---------------------------------------------------------------------------

async def test_returns_true_on_direct_click():
    page, btn_loc, _ = _page_first_selector_present()

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await expand_description(page)

    assert result is True
    btn_loc.click.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Direct click fails, fallback to span click succeeds
# ---------------------------------------------------------------------------

async def test_falls_back_to_span_when_direct_click_raises():
    span_loc = MagicMock()
    span_loc.count = AsyncMock(return_value=1)
    span_loc.click = AsyncMock()
    span_loc.first = span_loc

    btn_loc = MagicMock()
    btn_loc.count = AsyncMock(return_value=1)
    btn_loc.click = AsyncMock(side_effect=Exception('pointer-events blocked'))
    btn_loc.locator = MagicMock(return_value=span_loc)
    btn_loc.first = btn_loc

    empty_loc = MagicMock()
    empty_loc.count = AsyncMock(return_value=0)
    empty_loc.first = empty_loc

    first_selector = _EXPAND_SELECTORS[0]

    def locator_side(selector: str) -> MagicMock:
        return btn_loc if selector == first_selector else empty_loc

    page = MagicMock()
    page.locator = MagicMock(side_effect=locator_side)

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await expand_description(page)

    assert result is True
    span_loc.click.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Button found, no span and direct click also fails → returns False
# ---------------------------------------------------------------------------

async def test_returns_false_when_direct_and_span_both_fail():
    span_loc = MagicMock()
    span_loc.count = AsyncMock(return_value=0)
    span_loc.first = span_loc

    btn_loc = MagicMock()
    btn_loc.count = AsyncMock(return_value=1)
    btn_loc.click = AsyncMock(side_effect=Exception('click failed'))
    btn_loc.locator = MagicMock(return_value=span_loc)
    btn_loc.first = btn_loc

    empty_loc = MagicMock()
    empty_loc.count = AsyncMock(return_value=0)
    empty_loc.first = empty_loc

    first_selector = _EXPAND_SELECTORS[0]

    def locator_side(selector: str) -> MagicMock:
        return btn_loc if selector == first_selector else empty_loc

    page = MagicMock()
    page.locator = MagicMock(side_effect=locator_side)

    result = await expand_description(page)
    assert result is False


# ---------------------------------------------------------------------------
# page.locator raises on every call — must not propagate
# ---------------------------------------------------------------------------

async def test_returns_false_on_playwright_error():
    page = MagicMock()
    page.locator = MagicMock(side_effect=Exception('playwright exploded'))

    result = await expand_description(page)

    assert result is False


# ---------------------------------------------------------------------------
# Second selector in the list works when first is absent
# ---------------------------------------------------------------------------

async def test_falls_through_to_second_selector():
    btn_loc = MagicMock()
    btn_loc.count = AsyncMock(return_value=1)
    btn_loc.click = AsyncMock()
    btn_loc.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0), first=MagicMock()))
    btn_loc.first = btn_loc

    empty_loc = MagicMock()
    empty_loc.count = AsyncMock(return_value=0)
    empty_loc.first = empty_loc

    second_selector = _EXPAND_SELECTORS[1]

    def locator_side(selector: str) -> MagicMock:
        return btn_loc if selector == second_selector else empty_loc

    page = MagicMock()
    page.locator = MagicMock(side_effect=locator_side)

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await expand_description(page)

    assert result is True
    btn_loc.click.assert_called_once_with(force=True)
