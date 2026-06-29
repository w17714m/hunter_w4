from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from src.core.models import MatchVerdict

if TYPE_CHECKING:
  from src.core.models import Offer, SkillMatch
  from src.embeddings.vector_store import LanceDbStore

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Profile context:
{fragmentos_rag}

Job offer:
Title: {titulo}
Company: {empresa}
Location: {ubicacion}

Skills found in the offer: {skills_encontrados}
Skills not found: {skills_faltantes}

Description:
{descripcion}

Evaluate whether this offer is suitable for the profile. Respond ONLY with valid JSON, no additional text:
{{"score": 0.0-1.0, "apto": true/false, "razon": "...", "puntos_favor": [...], "puntos_contra": [...]}}"""


def _extract_json(text: str) -> str:
  """Extract the first JSON block found in the text."""
  start = text.find('{')
  end = text.rfind('}')
  if start == -1 or end == -1 or end <= start:
    raise ValueError(f'No valid JSON found in response: {text[:200]}')
  return text[start:end + 1]


class OllamaJudgeError(Exception):
  pass


class OllamaJudge:
  """Evaluate an offer against the user profile using RAG + LLM (Ollama).

  Retrieves relevant profile fragments (namespace 'perfil') by vector similarity,
  builds the prompt with the SkillMatch and the Markdown description,
  and returns a typed MatchVerdict. Retries once if JSON parsing fails.
  """

  PROFILE_NAMESPACE = 'perfil'

  def __init__(
    self,
    store: LanceDbStore,
    base_url: str = 'http://localhost:11434',
    model: str = 'deepseek-r1:14b',
    top_k_profile: int = 3,
    truncar_chars: int = 3000,
    timeout_s: float = 120.0,
  ) -> None:
    self.store = store
    self.base_url = base_url.rstrip('/')
    self.model = model
    self.top_k_profile = top_k_profile
    self.truncar_chars = truncar_chars
    self.timeout_s = timeout_s

  def judge(self, offer: Offer) -> MatchVerdict:
    """Evaluate the offer and return a MatchVerdict. Never returns None."""
    prompt = self._build_prompt(offer)
    raw = self._call_ollama(prompt)
    try:
      return self._parse_verdict(raw)
    except (ValueError, ValidationError) as exc:
      logger.warning('First parse attempt failed (%s). Retrying...', exc)
      raw2 = self._call_ollama(prompt)
      try:
        return self._parse_verdict(raw2)
      except (ValueError, ValidationError) as exc2:
        raise OllamaJudgeError(
          f'Judge did not produce a valid MatchVerdict after 2 attempts. '
          f'Last error: {exc2}. Response: {raw2[:300]}'
        ) from exc2

  def _build_prompt(self, offer: Offer) -> str:
    fragmentos = self._retrieve_profile_fragments(offer.descripcion_md)
    skill_match: SkillMatch | None = offer.skill_match
    skills_encontrados = skill_match.skills_encontrados if skill_match else []
    skills_faltantes = skill_match.skills_faltantes if skill_match else []

    return _PROMPT_TEMPLATE.format(
      fragmentos_rag=fragmentos,
      titulo=offer.titulo,
      empresa=offer.empresa or 'No especificada',
      ubicacion=offer.ubicacion or 'No especificada',
      skills_encontrados=', '.join(skills_encontrados) if skills_encontrados else 'ninguno',
      skills_faltantes=', '.join(skills_faltantes) if skills_faltantes else 'ninguno',
      descripcion=offer.descripcion_md[:self.truncar_chars],
    )

  def _retrieve_profile_fragments(self, query_text: str) -> str:
    results = self.store.search(
      namespace=self.PROFILE_NAMESPACE,
      query_text=query_text,
      top_k=self.top_k_profile,
    )
    if not results:
      return '(No indexed profile context)'
    return '\n\n---\n\n'.join(r['text'] for r in results)

  def _call_ollama(self, prompt: str) -> str:
    try:
      response = httpx.post(
        f'{self.base_url}/api/generate',
        json={
          'model': self.model,
          'prompt': prompt,
          'stream': False,
          'format': 'json',
        },
        timeout=self.timeout_s,
      )
    except httpx.TransportError as exc:
      raise OllamaJudgeError(f'Could not connect to Ollama at {self.base_url}: {exc}') from exc

    if response.status_code != 200:
      raise OllamaJudgeError(
        f'Ollama responded {response.status_code}: {response.text[:200]}'
      )

    data = response.json()
    return data.get('response', '')

  def _parse_verdict(self, raw: str) -> MatchVerdict:
    json_str = _extract_json(raw)
    data = json.loads(json_str)
    return MatchVerdict.model_validate(data)
