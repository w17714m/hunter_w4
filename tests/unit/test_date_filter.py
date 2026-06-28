from datetime import date, timedelta

from src.core.models import Offer
from src.filters.date_filter import DateFilter


def build_offer(posted_date: date | None) -> Offer:
  return Offer(
    id='offer-date',
    fuente='elempleo',
    url='https://www.elempleo.com/oferta/1',
    titulo='Backend Python',
    posted_date=posted_date,
    descripcion_md='## Oferta\n\nPython y SQL.',
  )


def test_date_filter_passes_when_date_missing() -> None:
  result = DateFilter(max_days=7).apply(build_offer(posted_date=None), today=date(2026, 6, 22))
  assert result.pasa is True
  assert result.motivo == 'missing_date_assumed_recent'


def test_date_filter_passes_on_exact_cutoff() -> None:
  today = date(2026, 6, 22)
  cutoff_date = today - timedelta(days=7)
  result = DateFilter(max_days=7).apply(build_offer(posted_date=cutoff_date), today=today)
  assert result.pasa is True
  assert result.motivo == 'recent'


def test_date_filter_fails_when_offer_is_old() -> None:
  today = date(2026, 6, 22)
  old_date = today - timedelta(days=8)
  result = DateFilter(max_days=7).apply(build_offer(posted_date=old_date), today=today)
  assert result.pasa is False
  assert result.motivo == 'older_than_max_days'

