import pytest

from src.core.models import Offer
from src.filters import SkillFilter


def _offer(text: str) -> Offer:
    return Offer(
        id='test-id',
        fuente='linkedin',
        url='https://linkedin.com/jobs/view/999',
        titulo='Dev',
        descripcion_md=text,
    )


def test_skill_filter_matches_required_skills_with_partial_match() -> None:
    offer = _offer('We need Python and AWS experience. SQL is a plus.')
    result = SkillFilter(
        required_skills=['Python', 'FastAPI', 'AWS'],
        umbral_match=0.5,
    ).match(offer)

    assert result.skills_encontrados == ['Python', 'AWS']
    assert result.skills_faltantes == ['FastAPI']
    assert result.fraccion == pytest.approx(2 / 3)
    assert result.pasa is True


def test_skill_match_handles_empty_required_skills() -> None:
    offer = _offer('Python developer needed.')
    result = SkillFilter(
        required_skills=[],
        umbral_match=1.0,
    ).match(offer)

    assert result.skills_encontrados == []
    assert result.skills_faltantes == []
    assert result.fraccion == 1.0
    assert result.pasa is True


def test_skill_match_threshold_edges() -> None:
    offer = _offer('Java developer with Spring Boot experience.')
    low_threshold = SkillFilter(required_skills=['Python'], umbral_match=0.0).match(offer)
    high_threshold = SkillFilter(required_skills=['Python'], umbral_match=1.0).match(offer)

    assert low_threshold.pasa is True
    assert high_threshold.pasa is False
