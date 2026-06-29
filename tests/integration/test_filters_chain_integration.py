from datetime import date

from src.core.models import Offer
from src.filters.date_filter import DateFilter
from src.filters.language import LanguageFilter
from src.filters.skill_filter import SkillFilter


def test_filters_chain_with_real_markdown_offer() -> None:
  offer = Offer(
    id='offer-chain',
    fuente='elempleo',
    url='https://www.elempleo.com/oferta/chain',
    titulo='Backend Engineer',
    posted_date=date(2026, 6, 20),
    descripcion_md=(
      '## Vacante Backend Python\n\n'
      'Buscamos un desarrollador backend para construir APIs en una plataforma de pagos.\n'
      'El rol requiere colaboracion con equipos de producto, diseno y datos.\n\n'
      'Requisitos:\n'
      '- Python\n'
      '- FastAPI\n'
      '- SQL\n'
      '- Comunicacion efectiva en espanol\n'
    ),
  )

  date_result = DateFilter(max_days=7).apply(offer, today=date(2026, 6, 22))
  language_result = LanguageFilter(['ES', 'EN']).apply(offer)
  offer_with_match = SkillFilter(['Python', 'FastAPI', 'Docker'], 2 / 3).attach(offer)

  assert date_result.pasa is True
  assert language_result.pasa is True
  assert offer_with_match.skill_match is not None
  assert offer_with_match.skill_match.pasa is True
  assert offer_with_match.skill_match.skills_faltantes == ['Docker']
