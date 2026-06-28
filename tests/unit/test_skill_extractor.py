from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.filters.skill_extractor import LLMSkillExtractor, LLMSkillExtractorError


def _make_extractor() -> LLMSkillExtractor:
    return LLMSkillExtractor(base_url='http://localhost:11434', model='qwen2.5:3b')


def _mock_httpx_response(body: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.json.return_value = {'message': {'content': body}}
    return resp


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_direct_array():
    ext = _make_extractor()
    result = ext._parse_response('["Python", "FastAPI", "Docker"]')
    assert result == ['Python', 'FastAPI', 'Docker']


def test_parse_response_wrapped_in_object():
    ext = _make_extractor()
    raw = json.dumps({'technologies': ['AWS', 'Kubernetes', 'Terraform']})
    result = ext._parse_response(raw)
    assert result == ['AWS', 'Kubernetes', 'Terraform']


def test_parse_response_array_inside_text():
    ext = _make_extractor()
    # LLM preamble before the JSON array
    raw = 'Here are the skills: ["React", "TypeScript"] from the description.'
    result = ext._parse_response(raw)
    assert result == ['React', 'TypeScript']


def test_parse_response_empty_string_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('') == []


def test_parse_response_invalid_json_returns_empty():
    ext = _make_extractor()
    assert ext._parse_response('{bad json') == []


def test_parse_response_strips_whitespace_from_items():
    ext = _make_extractor()
    result = ext._parse_response('[" Python ", "  SQL  "]')
    assert result == ['Python', 'SQL']


# ---------------------------------------------------------------------------
# extract — happy path with mocked httpx
# ---------------------------------------------------------------------------

def test_extract_returns_list_of_strings():
    ext = _make_extractor()
    mock_resp = _mock_httpx_response('["Python", "FastAPI", "PostgreSQL"]')

    with patch('httpx.post', return_value=mock_resp):
        result = ext.extract('We need Python and FastAPI with PostgreSQL.')

    assert result == ['Python', 'FastAPI', 'PostgreSQL']


def test_extract_returns_empty_on_empty_description():
    ext = _make_extractor()
    assert ext.extract('') == []
    assert ext.extract('   ') == []


def test_extract_returns_empty_on_invalid_json_response():
    ext = _make_extractor()
    mock_resp = _mock_httpx_response('not json at all')

    with patch('httpx.post', return_value=mock_resp):
        result = ext.extract('Some job description here.')

    assert result == []


def test_extract_returns_empty_on_http_error():
    ext = _make_extractor()

    with patch('httpx.post', side_effect=Exception('connection refused')):
        result = ext.extract('Some job description here.')

    assert result == []


def test_extract_returns_empty_on_non_200_status():
    ext = _make_extractor()
    mock_resp = _mock_httpx_response('error', status=500)

    with patch('httpx.post', return_value=mock_resp):
        result = ext.extract('Backend developer with Python skills.')

    assert result == []


# ---------------------------------------------------------------------------
# _call_ollama — error handling
# ---------------------------------------------------------------------------

def test_call_ollama_raises_on_transport_error():
    import httpx as _httpx
    ext = _make_extractor()

    with patch('httpx.post', side_effect=_httpx.TransportError('no route')):
        with pytest.raises(LLMSkillExtractorError, match='Cannot connect'):
            ext._call_ollama('test prompt')


def test_call_ollama_raises_on_non_200():
    ext = _make_extractor()
    mock_resp = _mock_httpx_response('Internal error', status=503)

    with patch('httpx.post', return_value=mock_resp):
        with pytest.raises(LLMSkillExtractorError, match='503'):
            ext._call_ollama('test prompt')
