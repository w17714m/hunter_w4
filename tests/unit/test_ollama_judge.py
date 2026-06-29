from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.judge.ollama_judge import OllamaJudge, OllamaJudgeError, _extract_json


# ---------------------------------------------------------------------------
# _extract_json helper
# ---------------------------------------------------------------------------

def test_extract_json_clean():
  raw = '{"score": 0.8, "apto": true, "razon": "ok", "puntos_favor": [], "puntos_contra": []}'
  result = _extract_json(raw)
  assert json.loads(result)['score'] == 0.8


def test_extract_json_with_preamble():
  raw = 'Aquí está mi respuesta: {"score": 0.5, "apto": false, "razon": "no", "puntos_favor": [], "puntos_contra": []}'
  result = _extract_json(raw)
  assert json.loads(result)['apto'] is False


def test_extract_json_no_json_raises():
  with pytest.raises(ValueError, match='No se encontró JSON'):
    _extract_json('Sin JSON aquí')


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

def _make_offer(skill_match: SkillMatch | None = None) -> Offer:
  return Offer(
    id='test-001',
    fuente='elempleo',
    url='https://example.com/job/1',
    titulo='Backend Developer',
    empresa='TechCo',
    ubicacion='Bogotá',
    posted_date=date(2024, 6, 1),
    descripcion_md='## Requisitos\n\nPython 3.10, FastAPI, Docker.',
    skill_match=skill_match,
  )


def _make_skill_match(encontrados=None, faltantes=None, pasa=True) -> SkillMatch:
  encontrados = encontrados or ['Python', 'Docker']
  faltantes = faltantes or []
  return SkillMatch(
    skills_encontrados=encontrados,
    skills_faltantes=faltantes,
    fraccion=len(encontrados) / (len(encontrados) + len(faltantes)) if (encontrados or faltantes) else 1.0,
    pasa=pasa,
  )


def _make_store_with_results(texts: list[str] | None = None) -> MagicMock:
  store = MagicMock()
  results = [{'id': f'sec_{i}', 'text': t, 'score': 0.1} for i, t in enumerate(texts or [])]
  store.search.return_value = results
  return store


def _make_ollama_response(score=0.8, apto=True) -> dict:
  return {
    'response': json.dumps({
      'score': score,
      'apto': apto,
      'razon': 'Buen match de skills',
      'puntos_favor': ['Python', 'Docker'],
      'puntos_contra': [],
    })
  }


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def test_prompt_includes_skill_match():
  store = _make_store_with_results(['Fragmento del perfil'])
  judge = OllamaJudge(store=store, model='llama3')
  offer = _make_offer(skill_match=_make_skill_match(['Python'], ['Java']))

  prompt = judge._build_prompt(offer)

  assert 'Python' in prompt
  assert 'Java' in prompt
  assert 'Backend Developer' in prompt
  assert 'TechCo' in prompt
  assert 'Bogotá' in prompt
  assert 'Fragmento del perfil' in prompt


def test_prompt_truncates_descripcion():
  store = _make_store_with_results()
  judge = OllamaJudge(store=store, truncar_chars=10)
  offer = _make_offer()

  prompt = judge._build_prompt(offer)

  # The full description is more than 10 chars, so it must be truncated
  assert offer.descripcion_md[:10] in prompt
  assert offer.descripcion_md[10:] not in prompt


def test_prompt_no_skill_match_shows_ninguno():
  store = _make_store_with_results(['Perfil: developer'])
  judge = OllamaJudge(store=store)
  offer = _make_offer(skill_match=None)

  prompt = judge._build_prompt(offer)

  assert 'ninguno' in prompt


def test_prompt_no_profile_fragments_shows_fallback():
  store = _make_store_with_results([])  # empty
  judge = OllamaJudge(store=store)
  offer = _make_offer()

  prompt = judge._build_prompt(offer)

  assert 'Sin contexto de perfil' in prompt


# ---------------------------------------------------------------------------
# judge() — parseo exitoso
# ---------------------------------------------------------------------------

def test_judge_returns_verdict_on_success():
  store = _make_store_with_results(['Soy dev Python'])
  judge = OllamaJudge(store=store)
  offer = _make_offer(_make_skill_match())

  with patch('httpx.post') as mock_post:
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = _make_ollama_response(score=0.9, apto=True)

    verdict = judge.judge(offer)

  assert isinstance(verdict, MatchVerdict)
  assert verdict.score == pytest.approx(0.9)
  assert verdict.apto is True


# ---------------------------------------------------------------------------
# judge() — reintento en mal parseo
# ---------------------------------------------------------------------------

def test_judge_retries_on_bad_json():
  store = _make_store_with_results(['Contexto'])
  judge = OllamaJudge(store=store)
  offer = _make_offer()

  bad_response = MagicMock()
  bad_response.status_code = 200
  bad_response.json.return_value = {'response': 'No es JSON válido'}

  good_response = MagicMock()
  good_response.status_code = 200
  good_response.json.return_value = _make_ollama_response(score=0.6, apto=False)

  with patch('httpx.post', side_effect=[bad_response, good_response]):
    verdict = judge.judge(offer)

  assert verdict.apto is False
  assert verdict.score == pytest.approx(0.6)


def test_judge_raises_after_two_failures():
  store = _make_store_with_results()
  judge = OllamaJudge(store=store)
  offer = _make_offer()

  bad = MagicMock()
  bad.status_code = 200
  bad.json.return_value = {'response': 'respuesta mal formada'}

  with patch('httpx.post', side_effect=[bad, bad]):
    with pytest.raises(OllamaJudgeError, match='2 intentos'):
      judge.judge(offer)


# ---------------------------------------------------------------------------
# judge() — errores de red
# ---------------------------------------------------------------------------

def test_judge_raises_on_network_error():
  import httpx as _httpx
  store = _make_store_with_results()
  judge = OllamaJudge(store=store)
  offer = _make_offer()

  with patch('httpx.post', side_effect=_httpx.ConnectError('timeout')):
    with pytest.raises(OllamaJudgeError, match='conectar'):
      judge.judge(offer)


def test_judge_raises_on_non_200():
  store = _make_store_with_results()
  judge = OllamaJudge(store=store)
  offer = _make_offer()

  error_resp = MagicMock()
  error_resp.status_code = 500
  error_resp.text = 'Internal Server Error'

  with patch('httpx.post', return_value=error_resp):
    with pytest.raises(OllamaJudgeError, match='500'):
      judge.judge(offer)
