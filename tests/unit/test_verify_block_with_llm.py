"""Tests para _verify_block_with_llm: verificación LLM de falsos positivos
del detector heurístico de bloqueo antes de rotar IP."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


# ---------------------------------------------------------------------------
# LLM finds real description text despite the heuristic block — false positive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_finds_description_text_returns_ok_llm():
    page = MagicMock()
    page.content = AsyncMock(return_value='<html><body>Job content</body></html>')

    llm_result = {'description_text': 'Full real job description', 'expand_selector': ''}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        collector = _make_collector()
        result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is not None
    html, status = result
    assert html == 'Full real job description'
    assert status == 'ok_llm'


@pytest.mark.asyncio
async def test_llm_description_with_selector_saves_to_db():
    repo = MagicMock()
    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')

    llm_result = {'description_text': 'Real description', 'expand_selector': '[data-testid="more"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        collector = _make_collector(repo=repo)
        await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    repo.kv_set.assert_called_once_with('linkedin_expand_selector', '[data-testid="more"]')


# ---------------------------------------------------------------------------
# LLM finds only an expand selector — click succeeds — false positive confirmed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_selector_click_succeeds_returns_ok_llm():
    def locator_side(selector: str) -> MagicMock:
        if selector == '[data-testid="show-more"]':
            return _locator_with(count=1)
        return _locator_with(count=1, html='<p>Description after click</p>')

    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')
    page.locator = MagicMock(side_effect=locator_side)

    llm_result = {'description_text': '', 'expand_selector': '[data-testid="show-more"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is not None
    html, status = result
    assert 'Description after click' in html
    assert status == 'ok_llm'


@pytest.mark.asyncio
async def test_llm_selector_click_success_saves_to_db():
    repo = MagicMock()

    def locator_side(selector: str) -> MagicMock:
        if selector == '[data-testid="show-more"]':
            return _locator_with(count=1)
        return _locator_with(count=1, html='<p>Content</p>')

    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')
    page.locator = MagicMock(side_effect=locator_side)

    llm_result = {'description_text': '', 'expand_selector': '[data-testid="show-more"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector(repo=repo)
            await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    repo.kv_set.assert_called_once_with('linkedin_expand_selector', '[data-testid="show-more"]')


# ---------------------------------------------------------------------------
# LLM confirms genuine block — returns None, caller proceeds to rotate IP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_confirms_real_block_returns_none():
    page = MagicMock()
    page.content = AsyncMock(return_value='<html><body>Authwall</body></html>')

    llm_result = {'description_text': '', 'expand_selector': ''}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        collector = _make_collector()
        result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is None


@pytest.mark.asyncio
async def test_llm_selector_not_found_in_dom_returns_none():
    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')
    page.locator = MagicMock(return_value=_locator_with(count=0))

    llm_result = {'description_text': '', 'expand_selector': '[data-testid="ghost"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        collector = _make_collector()
        result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is None


@pytest.mark.asyncio
async def test_llm_click_succeeds_but_content_still_empty_returns_none():
    def locator_side(selector: str) -> MagicMock:
        if selector == '[data-testid="show-more"]':
            return _locator_with(count=1)
        return _locator_with(count=0)

    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')
    page.locator = MagicMock(side_effect=locator_side)

    llm_result = {'description_text': '', 'expand_selector': '[data-testid="show-more"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is None


# ---------------------------------------------------------------------------
# Failures never propagate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_extraction_exception_returns_none_silently():
    page = MagicMock()
    page.content = AsyncMock(side_effect=RuntimeError('boom'))

    collector = _make_collector()
    result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is None


@pytest.mark.asyncio
async def test_repo_none_does_not_crash_on_selector_save():
    page = MagicMock()
    page.content = AsyncMock(return_value='<html></html>')

    llm_result = {'description_text': 'Some description', 'expand_selector': '[data-testid="x"]'}
    with patch('asyncio.to_thread', new=AsyncMock(return_value=llm_result)):
        collector = _make_collector(repo=None)
        result = await collector._verify_block_with_llm(page, 'https://linkedin.com/jobs/view/1', attempt=0)

    assert result is not None
    assert result[1] == 'ok_llm'
