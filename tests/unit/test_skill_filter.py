from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.models import Offer
from src.filters.skill_filter import SkillFilter


def build_offer(text: str) -> Offer:
  return Offer(
    id='offer-skill',
    fuente='linkedin',
    url='https://linkedin.com/jobs/view/555',
    titulo='Python Developer',
    descripcion_md=text,
  )


def _extractor_returning(skills: list[str]) -> MagicMock:
  ext = MagicMock()
  ext.extract.return_value = skills
  return ext


# ---------------------------------------------------------------------------
# Original fallback logic (no extractor)
# ---------------------------------------------------------------------------

def test_skill_filter_passes_when_all_skills_present() -> None:
  offer = build_offer('Python, FastAPI, Docker, AWS y SQL.')
  result = SkillFilter(['Python', 'FastAPI', 'Docker'], 1.0).match(offer)
  assert result.pasa is True
  assert result.skills_faltantes == []


def test_skill_filter_fails_when_no_skill_present() -> None:
  offer = build_offer('Trabajo con JavaScript y React.')
  result = SkillFilter(['Python', 'FastAPI'], 0.5).match(offer)
  assert result.pasa is False
  assert result.skills_encontrados == []


def test_skill_filter_accepts_fraction_exactly_on_threshold() -> None:
  offer = build_offer('Python y SQL.')
  result = SkillFilter(['Python', 'FastAPI'], 0.5).match(offer)
  assert result.pasa is True
  assert result.fraccion == 0.5


def test_skill_filter_rejects_below_threshold() -> None:
  offer = build_offer('Docker solamente.')
  result = SkillFilter(['Python', 'FastAPI', 'Docker'], 0.5).match(offer)
  assert result.pasa is False


def test_skill_filter_is_case_insensitive() -> None:
  offer = build_offer('Buscamos PYTHON developer.')
  result = SkillFilter(['Python'], 1.0).match(offer)
  assert result.pasa is True
  assert result.skills_encontrados == ['Python']


def test_skill_filter_avoids_substring_false_positives() -> None:
  offer = build_offer('Experiencia con AWSOME tooling.')
  result = SkillFilter(['AWS'], 1.0).match(offer)
  assert result.pasa is False


def test_skill_filter_with_empty_required_list_passes() -> None:
  offer = build_offer('Cualquier descripcion.')
  result = SkillFilter([], 1.0).match(offer)
  assert result.pasa is True
  assert result.fraccion == 1.0


def test_skill_filter_attach_populates_offer_skill_match() -> None:
  offer = build_offer('Python y SQL.')
  filtered_offer = SkillFilter(['Python', 'SQL'], 1.0).attach(offer)

  assert offer.skill_match is None
  assert filtered_offer.skill_match is not None
  assert filtered_offer.skill_match.skills_encontrados == ['Python', 'SQL']


# ---------------------------------------------------------------------------
# LLM extractor path
# ---------------------------------------------------------------------------

def test_skill_filter_with_extractor_fraction_over_offer_skills() -> None:
  """fraccion = yaml_skills_in_offer / total_offer_skills, not over yaml list."""
  # Offer asks for 4 skills; user YAML covers 2 → fraction = 0.5
  ext = _extractor_returning(['Python', 'Java', 'Kubernetes', 'MongoDB'])
  offer = build_offer('We need Python, Java, Kubernetes, and MongoDB.')
  result = SkillFilter(['Python', 'Java', 'Docker'], 0.4, extractor=ext).match(offer)

  assert result.fraccion == pytest.approx(0.5)
  assert result.pasa is True
  assert 'Python' in result.skills_encontrados
  assert 'Java' in result.skills_encontrados


def test_skill_filter_with_extractor_passes_with_partial_coverage() -> None:
  # Offer has 3 skills; user covers 2 (67%). Threshold 0.50 → pass.
  ext = _extractor_returning(['Python', 'FastAPI', 'MongoDB'])
  offer = build_offer('Role requires Python, FastAPI, MongoDB.')
  result = SkillFilter(['Python', 'FastAPI', 'Docker', 'AWS'], 0.50, extractor=ext).match(offer)

  assert result.fraccion == pytest.approx(2 / 3)
  assert result.pasa is True


def test_skill_filter_with_extractor_fails_when_coverage_low() -> None:
  # Offer has 5 skills; user covers 1 (20%). Threshold 0.30 → fail.
  ext = _extractor_returning(['Go', 'Rust', 'Kubernetes', 'Istio', 'eBPF'])
  offer = build_offer('Need Go, Rust, Kubernetes, Istio, eBPF.')
  result = SkillFilter(['Go', 'Python', 'Docker'], 0.30, extractor=ext).match(offer)

  assert result.fraccion == pytest.approx(1 / 5)
  assert result.pasa is False


def test_skill_filter_falls_back_to_original_when_extractor_returns_empty() -> None:
  # Extractor returns [] → original denominator logic kicks in
  ext = _extractor_returning([])
  offer = build_offer('Python y SQL.')
  result = SkillFilter(['Python', 'FastAPI'], 0.5, extractor=ext).match(offer)

  # Original logic: 1/2 = 0.5, which equals the threshold → passes
  assert result.fraccion == 0.5
  assert result.pasa is True


def test_skill_filter_extractor_called_with_offer_description() -> None:
  ext = _extractor_returning(['Python'])
  offer = build_offer('Python developer role.')
  SkillFilter(['Python'], 0.5, extractor=ext).match(offer)
  ext.extract.assert_called_once_with('Python developer role.')
