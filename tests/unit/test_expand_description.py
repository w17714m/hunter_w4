from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.stealth.playwright_stealth_extras import expand_description


def _make_locator(count: int = 1) -> MagicMock:
    """Build a minimal Playwright locator mock."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.click = AsyncMock()
    loc.locator = MagicMock(return_value=loc)  # chaining .locator('span') returns self
    loc.first = loc
    return loc


def _make_page(btn_count: int = 1, span_count: int = 1) -> MagicMock:
    """Build a page mock whose expandable-text-button returns btn_count elements."""
    span_loc = _make_locator(span_count)
    btn_loc = _make_locator(btn_count)
    btn_loc.locator = MagicMock(return_value=span_loc)
    btn_loc.first = btn_loc

    page = MagicMock()
    page.locator = MagicMock(return_value=btn_loc)
    return page, btn_loc, span_loc


# ---------------------------------------------------------------------------
# No button present
# ---------------------------------------------------------------------------

async def test_returns_false_when_no_button():
    page, btn_loc, _ = _make_page(btn_count=0)
    result = await expand_description(page)
    assert result is False
    btn_loc.click.assert_not_called()


# ---------------------------------------------------------------------------
# Button present but inner span missing
# ---------------------------------------------------------------------------

async def test_returns_false_when_span_missing():
    page, btn_loc, span_loc = _make_page(btn_count=1, span_count=0)
    result = await expand_description(page)
    assert result is False
    span_loc.click.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path — button and span found, click dispatched with force=True
# ---------------------------------------------------------------------------

async def test_clicks_inner_span_with_force_true():
    page, _, span_loc = _make_page(btn_count=1, span_count=1)

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await expand_description(page)

    assert result is True
    span_loc.click.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Playwright exception must not propagate
# ---------------------------------------------------------------------------

async def test_returns_false_on_playwright_error():
    page = MagicMock()
    page.locator.side_effect = Exception('playwright exploded')

    result = await expand_description(page)

    assert result is False


# ---------------------------------------------------------------------------
# Click raises — still returns False, no exception
# ---------------------------------------------------------------------------

async def test_returns_false_when_click_raises():
    page, _, span_loc = _make_page(btn_count=1, span_count=1)
    span_loc.click = AsyncMock(side_effect=Exception('click failed'))

    result = await expand_description(page)

    assert result is False
