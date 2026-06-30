"""Tests que verifican que _paginate_and_collect llama al LLM con el HTML
del card para extraer el nombre de empresa — sin selectores CSS hardcodeados."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.collectors.linkedin import LinkedInCollector


def _make_collector(**kwargs) -> LinkedInCollector:
    return LinkedInCollector(
        ollama_base_url='http://localhost:11434',
        extractor_company_model='qwen3:8b',
        **kwargs,
    )


def _make_page(cards: list[dict]) -> MagicMock:
    """Simula una página con una sola carga de cards (sin paginación)."""
    page = MagicMock()
    page.wait_for_selector = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[
        len(cards),   # primera llamada: count para estabilización
        len(cards),   # segunda llamada: count estabilizado (igual → sale del loop)
        cards,        # tercera llamada: retorna los cards
    ])
    # _click_next_page busca el botón de siguiente — retorna count=0 para terminar paginación
    next_loc = MagicMock()
    next_loc.count = AsyncMock(return_value=0)
    next_loc.first = next_loc
    page.locator = MagicMock(return_value=next_loc)
    return page


# ---------------------------------------------------------------------------
# El LLM es llamado con el HTML del card (no con selectores hardcodeados)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_called_with_card_html():
    """asyncio.to_thread debe recibir el outerHTML del <li> para cada card."""
    card_html = '<li data-occludable-job-id="111"><span>Acme Corp</span></li>'
    cards = [{'id': '111', 'card_html': card_html}]
    page = _make_page(cards)

    with patch('asyncio.to_thread', new=AsyncMock(return_value='Acme Corp')) as mock_thread:
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._paginate_and_collect(page, new_urls_needed=10)

    # to_thread fue llamado con el HTML del card
    assert mock_thread.call_count == 1
    # call_args: (func, html_arg) — el segundo argumento posicional es el HTML del card
    positional_args = mock_thread.call_args_list[0].args
    assert positional_args[1] == card_html


@pytest.mark.asyncio
async def test_empresa_extracted_by_llm_appears_in_result():
    """El nombre de empresa retornado por el LLM debe estar en la tupla (url, empresa)."""
    cards = [
        {'id': '111', 'card_html': '<li>card html empresa 1</li>'},
        {'id': '222', 'card_html': '<li>card html empresa 2</li>'},
    ]
    page = _make_page(cards)

    llm_responses = ['TechCo', 'Globex']

    with patch('asyncio.to_thread', new=AsyncMock(side_effect=llm_responses)):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._paginate_and_collect(page, new_urls_needed=10)

    assert len(result) == 2
    urls = [u for u, _ in result]
    empresas = [e for _, e in result]
    assert 'https://www.linkedin.com/jobs/view/111' in urls
    assert 'https://www.linkedin.com/jobs/view/222' in urls
    assert 'TechCo' in empresas
    assert 'Globex' in empresas


@pytest.mark.asyncio
async def test_llm_called_once_per_card():
    """Un card = una llamada al LLM. No debe haber llamadas extra."""
    cards = [
        {'id': '10', 'card_html': '<li>html 10</li>'},
        {'id': '20', 'card_html': '<li>html 20</li>'},
        {'id': '30', 'card_html': '<li>html 30</li>'},
    ]
    page = _make_page(cards)

    with patch('asyncio.to_thread', new=AsyncMock(return_value='')) as mock_thread:
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            await collector._paginate_and_collect(page, new_urls_needed=10)

    assert mock_thread.call_count == 3


@pytest.mark.asyncio
async def test_llm_returns_empty_empresa_still_included_in_result():
    """Si el LLM no puede extraer empresa (retorna ''), la URL sigue en el resultado."""
    cards = [{'id': '555', 'card_html': '<li>html sin empresa</li>'}]
    page = _make_page(cards)

    with patch('asyncio.to_thread', new=AsyncMock(return_value='')):
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._paginate_and_collect(page, new_urls_needed=10)

    assert len(result) == 1
    url, empresa = result[0]
    assert url == 'https://www.linkedin.com/jobs/view/555'
    assert empresa == ''


@pytest.mark.asyncio
async def test_no_hardcoded_company_selectors_in_js():
    """El JS que extrae los cards NO debe contener selectores de empresa hardcodeados.

    Regresión: la versión anterior usaba querySelector con clase CSS para extraer
    la empresa directamente en JS. Eso es frágil porque LinkedIn rota los nombres
    de clase. Ahora debe extraer solo el outerHTML y delegar la extracción al LLM.
    """
    import inspect
    from src.collectors.linkedin import LinkedInCollector

    source = inspect.getsource(LinkedInCollector._wait_and_extract_ids)

    # Selectores de empresa que NO deben aparecer en el código JS
    forbidden = [
        'job-card-container__primary-description',
        'job-card-container__company-name',
        'artdeco-entity-lockup__subtitle',
        'data-entity-type="COMPANY"',
    ]
    for selector in forbidden:
        assert selector not in source, (
            f'Selector hardcodeado encontrado en _wait_and_extract_ids: "{selector}". '
            'La extracción de empresa debe hacerse via LLM, no con selectores CSS.'
        )

    # El método SÍ debe extraer outerHTML
    assert 'outerHTML' in source


@pytest.mark.asyncio
async def test_url_deduplication_does_not_call_llm_twice_for_same_id():
    """Cards duplicados (mismo ID) no deben generar dos llamadas al LLM."""
    cards = [
        {'id': '111', 'card_html': '<li>first</li>'},
        {'id': '111', 'card_html': '<li>duplicate</li>'},
    ]
    page = _make_page(cards)

    with patch('asyncio.to_thread', new=AsyncMock(return_value='Acme')) as mock_thread:
        with patch('asyncio.sleep', new=AsyncMock()):
            collector = _make_collector()
            result = await collector._paginate_and_collect(page, new_urls_needed=10)

    # Solo un resultado único (deduplicado por URL)
    assert len(result) == 1
    # Solo una llamada al LLM
    assert mock_thread.call_count == 1
