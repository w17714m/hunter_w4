from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.stealth.html_description_extractor import HTMLDescriptionExtractor, HTMLDescriptionExtractorError


def _make_extractor() -> HTMLDescriptionExtractor:
    return HTMLDescriptionExtractor(base_url='http://localhost:11434', model='deepseek-r1:14b')


def _mock_response(body: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.json.return_value = {'message': {'content': body}}
    return resp


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_description_text():
    ext = _make_extractor()
    raw = json.dumps({'description_text': 'Senior Python Developer.', 'expand_selector': ''})
    result = ext._parse_response(raw)
    assert result['description_text'] == 'Senior Python Developer.'
    assert result['expand_selector'] == ''


def test_parse_response_expand_selector():
    ext = _make_extractor()
    raw = json.dumps({'description_text': '', 'expand_selector': '[data-testid="see-more"]'})
    result = ext._parse_response(raw)
    assert result['expand_selector'] == '[data-testid="see-more"]'
    assert result['description_text'] == ''


def test_parse_response_strips_think_blocks():
    ext = _make_extractor()
    payload = json.dumps({'description_text': 'Backend dev', 'expand_selector': ''})
    raw = f'<think>Analyzing the DOM...</think>\n{payload}'
    result = ext._parse_response(raw)
    assert result['description_text'] == 'Backend dev'


def test_parse_response_json_embedded_in_text():
    ext = _make_extractor()
    payload = json.dumps({'description_text': 'Dev role', 'expand_selector': ''})
    raw = f'Here is my result: {payload}'
    result = ext._parse_response(raw)
    assert result['description_text'] == 'Dev role'


def test_parse_response_malformed_returns_empty():
    ext = _make_extractor()
    result = ext._parse_response('{invalid json}')
    assert result == {'description_text': '', 'expand_selector': ''}


def test_parse_response_empty_string_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('') == {'description_text': '', 'expand_selector': ''}


def test_parse_response_only_think_block_returns_empty():
    ext = _make_extractor()
    result = ext._parse_response('<think>nothing useful</think>')
    assert result == {'description_text': '', 'expand_selector': ''}


# ---------------------------------------------------------------------------
# extract — httpx mocked
# ---------------------------------------------------------------------------

def test_extract_returns_description_text():
    ext = _make_extractor()
    payload = json.dumps({'description_text': 'We need a Python dev.', 'expand_selector': ''})
    with patch('httpx.post', return_value=_mock_response(payload)):
        result = ext.extract('<html><body><p>Job here</p></body></html>')
    assert result['description_text'] == 'We need a Python dev.'


def test_extract_returns_expand_selector():
    ext = _make_extractor()
    payload = json.dumps({'description_text': '', 'expand_selector': '[aria-label="Ver más"]'})
    with patch('httpx.post', return_value=_mock_response(payload)):
        result = ext.extract('<html><body><button aria-label="Ver más">...</button></body></html>')
    assert result['expand_selector'] == '[aria-label="Ver más"]'


def test_extract_empty_html_returns_empty():
    ext = _make_extractor()
    assert ext.extract('') == {'description_text': '', 'expand_selector': ''}
    assert ext.extract('   ') == {'description_text': '', 'expand_selector': ''}


def test_extract_returns_empty_on_generic_exception():
    ext = _make_extractor()
    with patch('httpx.post', side_effect=Exception('connection refused')):
        result = ext.extract('<html><body>Job content</body></html>')
    assert result == {'description_text': '', 'expand_selector': ''}


def test_extract_returns_empty_on_transport_error():
    import httpx as _httpx
    ext = _make_extractor()
    with patch('httpx.post', side_effect=_httpx.TransportError('timeout')):
        result = ext.extract('<html><body>Job</body></html>')
    assert result == {'description_text': '', 'expand_selector': ''}


def test_extract_returns_empty_on_non_200_status():
    ext = _make_extractor()
    with patch('httpx.post', return_value=_mock_response('Internal Server Error', status=500)):
        result = ext.extract('<html><body>Job content</body></html>')
    assert result == {'description_text': '', 'expand_selector': ''}


# ---------------------------------------------------------------------------
# _call_ollama — error propagation
# ---------------------------------------------------------------------------

def test_call_ollama_raises_on_transport_error():
    import httpx as _httpx
    ext = _make_extractor()
    with patch('httpx.post', side_effect=_httpx.TransportError('no route')):
        with pytest.raises(HTMLDescriptionExtractorError, match='Cannot connect'):
            ext._call_ollama('test prompt')


def test_call_ollama_raises_on_non_200():
    ext = _make_extractor()
    with patch('httpx.post', return_value=_mock_response('error', status=503)):
        with pytest.raises(HTMLDescriptionExtractorError, match='503'):
            ext._call_ollama('test prompt')


# ---------------------------------------------------------------------------
# _clean_html
# ---------------------------------------------------------------------------

def test_clean_html_removes_script_and_style():
    ext = _make_extractor()
    html = '<html><body><script>alert(1)</script><style>.x{color:red}</style><p>Job desc</p></body></html>'
    cleaned = ext._clean_html(html)
    assert '<script>' not in cleaned
    assert '<style>' not in cleaned
    assert 'Job desc' in cleaned


def test_clean_html_preserves_data_and_aria_attrs():
    ext = _make_extractor()
    html = '<button data-testid="see-more" aria-label="Ver más" class="btn">Ver más</button>'
    cleaned = ext._clean_html(html)
    assert 'data-testid="see-more"' in cleaned
    assert 'aria-label="Ver más"' in cleaned
    assert 'class=' not in cleaned


def test_clean_html_removes_class_and_id():
    ext = _make_extractor()
    html = '<div class="job-description" id="main"><p>Content</p></div>'
    cleaned = ext._clean_html(html)
    assert 'class=' not in cleaned
    assert 'id=' not in cleaned
    assert 'Content' in cleaned


def test_clean_html_truncates_to_max_chars():
    ext = _make_extractor()
    html = '<p>' + 'x' * 20_000 + '</p>'
    cleaned = ext._clean_html(html)
    assert len(cleaned) <= 12_000


def test_clean_html_removes_nav_and_header():
    ext = _make_extractor()
    html = '<header>Nav bar</header><nav>Links</nav><main><p>Job content</p></main>'
    cleaned = ext._clean_html(html)
    assert 'Nav bar' not in cleaned
    assert 'Links' not in cleaned
    assert 'Job content' in cleaned
