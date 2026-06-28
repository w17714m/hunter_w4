from __future__ import annotations

from datetime import date, timedelta

from src.core.models import Offer
from src.filters.results import FilterResult


class DateFilter:
  def __init__(self, max_days: int) -> None:
    if max_days < 0:
      raise ValueError('filtros.max_days debe ser >= 0')
    self.max_days = max_days

  def apply(self, offer: Offer, today: date | None = None) -> FilterResult:
    if offer.posted_date is None:
      return FilterResult(pasa=True, motivo='missing_date_assumed_recent')

    reference = today or date.today()
    cutoff = reference - timedelta(days=self.max_days)
    if offer.posted_date >= cutoff:
      return FilterResult(pasa=True, motivo='recent')
    return FilterResult(pasa=False, motivo='older_than_max_days')

