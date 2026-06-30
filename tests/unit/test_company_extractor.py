from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.stealth.company_extractor import CompanyExtractor, CompanyExtractorError


def _make_extractor() -> CompanyExtractor:
    return CompanyExtractor(base_url='http://localhost:11434', model='qwen3:8b')


def _mock_response(body: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.json.return_value = {'response': body}
    return resp


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_happy_path():
    ext = _make_extractor()
    raw = json.dumps({'empresa': 'Acme Corp'})
    assert ext._parse_response(raw) == 'Acme Corp'


def test_parse_response_empty_empresa():
    ext = _make_extractor()
    raw = json.dumps({'empresa': ''})
    assert ext._parse_response(raw) == ''


def test_parse_response_strips_think_block():
    ext = _make_extractor()
    payload = json.dumps({'empresa': 'TechCo'})
    raw = f'<think>reasoning</think>{payload}'
    assert ext._parse_response(raw) == 'TechCo'


def test_parse_response_json_embedded_in_text():
    ext = _make_extractor()
    payload = json.dumps({'empresa': 'Globex'})
    raw = f'Here is the result: {payload} end.'
    assert ext._parse_response(raw) == 'Globex'


def test_parse_response_malformed_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('{invalid}') == ''


def test_parse_response_empty_string_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('') == ''


def test_parse_response_only_think_block_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('<think>nothing</think>') == ''


# ---------------------------------------------------------------------------
# extract — httpx mocked
# ---------------------------------------------------------------------------

def test_extract_returns_company_name():
    ext = _make_extractor()
    payload = json.dumps({'empresa': 'Springerhead'})
    with patch('httpx.post', return_value=_mock_response(payload)):
        result = ext.extract('<li><span class="company">Springerhead</span></li>')
    assert result == 'Springerhead'


def test_extract_empty_html_returns_empty():
    ext = _make_extractor()
    assert ext.extract('') == ''
    assert ext.extract('   ') == ''


def test_extract_returns_empty_on_exception():
    ext = _make_extractor()
    with patch('httpx.post', side_effect=Exception('connection refused')):
        result = ext.extract('<li>some html</li>')
    assert result == ''


def test_extract_returns_empty_on_non_200():
    ext = _make_extractor()
    with patch('httpx.post', return_value=_mock_response('error', status=500)):
        result = ext.extract('<li>some html</li>')
    assert result == ''


# ---------------------------------------------------------------------------
# _clean_html
# ---------------------------------------------------------------------------

def test_clean_html_removes_script():
    ext = _make_extractor()
    html = '<li><script>alert(1)</script><span>Company</span></li>'
    cleaned = ext._clean_html(html)
    assert '<script>' not in cleaned
    assert 'Company' in cleaned


def test_clean_html_preserves_data_attrs():
    ext = _make_extractor()
    html = '<li data-job-id="123" class="card"><span>Corp</span></li>'
    cleaned = ext._clean_html(html)
    assert 'data-job-id="123"' in cleaned
    assert 'class=' not in cleaned


def test_clean_html_truncates():
    ext = _make_extractor()
    html = '<li>' + 'x' * 6_000 + '</li>'
    cleaned = ext._clean_html(html)
    assert len(cleaned) <= 4_000
