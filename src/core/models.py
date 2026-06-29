from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


OFFER_STATES = Literal[
  'new',
  'old',
  'other_lang',
  'low_skills',
  'low_sim',
  'matched',
  'notified',
  'notify_failed',
]


class SkillMatch(BaseModel):
  skills_encontrados: list[str]
  skills_faltantes: list[str]
  fraccion: float = Field(ge=0.0, le=1.0)
  pasa: bool
  skills_oferta: list[str] = []


class MatchVerdict(BaseModel):
  score: float = Field(ge=0.0, le=1.0)
  apto: bool
  razon: str
  puntos_favor: list[str]
  puntos_contra: list[str]


class Offer(BaseModel):
  id: str
  fuente: Literal['elempleo', 'linkedin', 'computrabajo']
  url: str
  titulo: str
  empresa: str | None = None
  ubicacion: str | None = None
  posted_date: date | None = None
  descripcion_md: str
  estado: OFFER_STATES = 'new'
  skill_match: SkillMatch | None = None
  similitud: float | None = Field(default=None, ge=0.0, le=1.0)
  veredicto: MatchVerdict | None = None

  @field_validator('descripcion_md')
  @classmethod
  def validate_descripcion_md(cls, value: str) -> str:
    normalized = value.strip()
    if not normalized:
      raise ValueError('descripcion_md no puede ser vacia')
    if re.search(r'<[a-zA-Z][^>]*>', normalized):
      raise ValueError('descripcion_md debe estar en markdown, no HTML crudo')
    return normalized

