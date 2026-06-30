from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.collectors.linkedin import LinkedInCollector


def _make_collector(repo=None) -> LinkedInCollector:
    return LinkedInCollector(
        ollama_base_url='http://localhost:11434',
        extractor_html_model='deepseek-r1:14b',
        repo=repo,
    )


def _locator_with(count: int, html: str = '') -> MagicMock:
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.inner_html = AsyncMock(return_value=html)
    loc.click = AsyncMock()
    loc.first = loc
    return loc


def _page_all_selectors_empty() -> MagicMock:
    """Page where every locator returns count=0 (no selector matches)."""
    loc = _locator_with(count=0)
    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError('timeout'))
    page.locator = MagicMock(return_value=loc)
    page.content = AsyncMock(return_value='<html><body>Job page</body></html>')
    return page


# ---------------------------------------------------------------------------
# Hardcoded selectors succeed — LLM never called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ok_when_hardcoded_selector_found():
    loc = _locator_with(count=1, html='<p>Description content</p>')
    page = MagicMock()
    page.wait_for_selector = AsyncMock()
    page.locator = MagicMock(return_value=loc)

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        collector = _make_collector()
        html, status = await collector._extract_description_html(page)

    assert status == 'ok'
    assert 'Description content' in html


# ---------------------------------------------------------------------------
# Saved selector from SQLite works — LLM never called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_saved_selector_works_returns_ok():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value='[data-testid="see-more"]')
    repo.kv_set = MagicMock()

    # Route by selector: saved selector finds button (count=1), DESCRIPTION_SELECTORS after click find content
    def locator_side(selector: str) -> MagicMock:
        if selector == '[data-testid="see-more"]':
            return _locator_with(count=1)  # the saved expand button exists
        # After click, re-iteration of DESCRIPTION_SELECTORS (first one matches)
        return _locator_with(count=1, html='<p>Full job description</p>')

    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError('timeout'))
    page.locator = MagicMock(side_effect=locator_side)
    page.content = AsyncMock(return_value='<html></html>')

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector(repo=repo)
            html, status = await collector._extract_description_html(page)

    assert status == 'ok'
    assert 'Full job description' in html


@pytest.mark.asyncio
async def test_saved_selector_fails_falls_through_to_llm():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value='[data-testid="old-selector"]')
    repo.kv_set = MagicMock()

    llm_result = {'description_text': 'Found via LLM.', 'expand_selector': ''}

    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.sleep', new=AsyncMock()):
            with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
                collector = _make_collector(repo=repo)
                html, status = await collector._extract_description_html(page)

    assert status == 'ok_llm'
    assert 'Found via LLM' in html


# ---------------------------------------------------------------------------
# All selectors fail — LLM returns description_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_returns_description_text():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value=None)
    repo.kv_set = MagicMock()

    llm_result = {'description_text': 'Senior Backend Engineer.', 'expand_selector': ''}
    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
            collector = _make_collector(repo=repo)
            html, status = await collector._extract_description_html(page)

    assert status == 'ok_llm'
    assert 'Senior Backend Engineer' in html


@pytest.mark.asyncio
async def test_llm_description_text_saves_selector_if_provided():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value=None)
    repo.kv_set = MagicMock()

    llm_result = {'description_text': 'Great role.', 'expand_selector': '[aria-label="Ver más"]'}
    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
            collector = _make_collector(repo=repo)
            await collector._extract_description_html(page)

    repo.kv_set.assert_called_once_with('linkedin_expand_selector', '[aria-label="Ver más"]')


# ---------------------------------------------------------------------------
# All selectors fail — LLM returns expand_selector, click succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_expand_selector_click_succeeds():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value=None)
    repo.kv_set = MagicMock()

    llm_result = {'description_text': '', 'expand_selector': '[data-testid="new-btn"]'}

    call_count = 0

    def locator_side(selector: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if selector == '[data-testid="new-btn"]':
            return _locator_with(count=1)
        # After click, re-iteration finds content
        if call_count > 6:
            return _locator_with(count=1, html='<p>Expanded description</p>')
        return _locator_with(count=0)

    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError('timeout'))
    page.locator = MagicMock(side_effect=locator_side)
    page.content = AsyncMock(return_value='<html></html>')

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.sleep', new=AsyncMock()):
            with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
                collector = _make_collector(repo=repo)
                html, status = await collector._extract_description_html(page)

    assert status == 'ok_llm'
    repo.kv_set.assert_called_once_with('linkedin_expand_selector', '[data-testid="new-btn"]')


# ---------------------------------------------------------------------------
# All fail including LLM — returns empty_description
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_returns_empty_gives_empty_description():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value=None)

    llm_result = {'description_text': '', 'expand_selector': ''}
    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
            collector = _make_collector(repo=repo)
            html, status = await collector._extract_description_html(page)

    assert status == 'empty_description'
    assert html == ''


@pytest.mark.asyncio
async def test_llm_raises_gives_empty_description_no_propagation():
    repo = MagicMock()
    repo.kv_get = MagicMock(return_value=None)

    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', side_effect=Exception('Ollama down')):
            collector = _make_collector(repo=repo)
            html, status = await collector._extract_description_html(page)

    assert status == 'empty_description'
    assert html == ''


# ---------------------------------------------------------------------------
# repo=None — no DB access, flow still works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_repo_llm_still_extracts():
    llm_result = {'description_text': 'Job description without repo.', 'expand_selector': ''}
    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
            collector = _make_collector(repo=None)
            html, status = await collector._extract_description_html(page)

    assert status == 'ok_llm'
    assert 'Job description without repo' in html


@pytest.mark.asyncio
async def test_no_repo_empty_description_no_crash():
    llm_result = {'description_text': '', 'expand_selector': ''}
    page = _page_all_selectors_empty()

    with patch('src.collectors.linkedin.expand_description', new=AsyncMock(return_value=False)):
        with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
            collector = _make_collector(repo=None)
            html, status = await collector._extract_description_html(page)

    assert status == 'empty_description'
