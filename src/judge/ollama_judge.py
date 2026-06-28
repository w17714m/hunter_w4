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
Contexto del perfil:
{fragmentos_rag}

Oferta:
Título: {titulo}
Empresa: {empresa}
Ubicación: {ubicacion}

Skills encontrados en la oferta: {skills_encontrados}
Skills no encontrados: {skills_faltantes}

Descripción:
{descripcion}

Evalúa si esta oferta es adecuada para el perfil. Responde ÚNICAMENTE en JSON válido, sin texto adicional:
{{"score": 0.0-1.0, "apto": true/false, "razon": "...", "puntos_favor": [...], "puntos_contra": [...]}}"""


def _extract_json(text: str) -> str:
  """Extrae el primer bloque JSON encontrado en el texto."""
  start = text.find('{')
  end = text.rfind('}')
  if start == -1 or end == -1 or end <= start:
    raise ValueError(f'No se encontró JSON válido en la respuesta: {text[:200]}')
  return text[start:end + 1]


class OllamaJudgeError(Exception):
  pass


class OllamaJudge:
  """Evalúa una oferta contra el perfil del usuario usando RAG + LLM (Ollama).

  Recupera fragmentos relevantes del perfil (namespace 'perfil') por similitud
  vectorial, construye el prompt con el SkillMatch y la descripción en Markdown,
  y retorna un MatchVerdict tipado. Reintenta una vez si el JSON no parsea.
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
    """Evalúa la oferta y retorna un MatchVerdict. Nunca retorna None."""
    prompt = self._build_prompt(offer)
    raw = self._call_ollama(prompt)
    try:
      return self._parse_verdict(raw)
    except (ValueError, ValidationError) as exc:
      logger.warning('Primer intento de parseo falló (%s). Reintentando...', exc)
      raw2 = self._call_ollama(prompt)
      try:
        return self._parse_verdict(raw2)
      except (ValueError, ValidationError) as exc2:
        raise OllamaJudgeError(
          f'El juez no produjo un MatchVerdict válido tras 2 intentos. '
          f'Último error: {exc2}. Respuesta: {raw2[:300]}'
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
      return '(Sin contexto de perfil indexado)'
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
      raise OllamaJudgeError(f'No se pudo conectar a Ollama en {self.base_url}: {exc}') from exc

    if response.status_code != 200:
      raise OllamaJudgeError(
        f'Ollama respondió {response.status_code}: {response.text[:200]}'
      )

    data = response.json()
    return data.get('response', '')

  def _parse_verdict(self, raw: str) -> MatchVerdict:
    json_str = _extract_json(raw)
    data = json.loads(json_str)
    return MatchVerdict.model_validate(data)
