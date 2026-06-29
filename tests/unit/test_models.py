from datetime import date

import pytest
from pydantic import ValidationError

from src.core.models import MatchVerdict, Offer, SkillMatch


def test_offer_accepts_markdown_description() -> None:
  offer = Offer(
    id='abc',
    fuente='elempleo',
    url='https://example.com/job',
    titulo='Python Developer',
    empresa='ACME',
    ubicacion='Bogota',
    posted_date=date(2026, 1, 10),
    descripcion_md='## Rol\n\nExperiencia con Python y FastAPI.',
    skill_match=SkillMatch(
      skills_encontrados=['Python'],
      skills_faltantes=['AWS'],
      fraccion=0.5,
      pasa=True,
    ),
  )

  assert offer.descripcion_md.startswith('## Rol')
  assert offer.estado == 'new'


def test_offer_rejects_empty_description() -> None:
  with pytest.raises(ValidationError, match='descripcion_md no puede ser vacia'):
    Offer(
      id='abc',
      fuente='linkedin',
      url='https://example.com/job',
      titulo='Python Developer',
      descripcion_md='   ',
    )


def test_offer_rejects_html_description() -> None:
  with pytest.raises(ValidationError, match='markdown, no HTML crudo'):
    Offer(
      id='abc',
      fuente='linkedin',
      url='https://example.com/job',
      titulo='Python Developer',
      descripcion_md='<div>texto</div>',
    )


def test_match_verdict_score_range() -> None:
  with pytest.raises(ValidationError):
    MatchVerdict(
      score=1.2,
      apto=True,
      razon='Buen encaje',
      puntos_favor=['Python'],
      puntos_contra=[],
    )

