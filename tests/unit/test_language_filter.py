from src.core.models import Offer
from src.filters.language import LanguageFilter


def build_offer(text: str) -> Offer:
  return Offer(
    id='offer-lang',
    fuente='linkedin',
    url='https://linkedin.com/jobs/view/123',
    titulo='Software Engineer',
    descripcion_md=text,
  )


def test_language_filter_accepts_spanish_and_english() -> None:
  filter_ = LanguageFilter(['ES', 'EN'])

  es_result = filter_.apply(build_offer('Buscamos desarrollador Python con experiencia en APIs.'))
  en_result = filter_.apply(build_offer('We are looking for a Python backend engineer.'))

  assert es_result.pasa is True and es_result.idioma_detectado == 'ES'
  assert en_result.pasa is True and en_result.idioma_detectado == 'EN'


def test_language_filter_rejects_non_allowed_language() -> None:
  result = LanguageFilter(['ES', 'EN']).apply(
    build_offer('Vaga para desenvolvedor de software com Python e SQL.'),
  )
  assert result.pasa is False
  assert result.idioma_detectado == 'PT'
  assert result.motivo == 'language_not_allowed'


def test_language_filter_handles_unknown_text() -> None:
  result = LanguageFilter(['ES', 'EN']).apply(build_offer('12345 !!! ...'))
  assert result.pasa is False
  assert result.idioma_detectado is None

