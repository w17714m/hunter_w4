from __future__ import annotations

from lingua import LanguageDetectorBuilder

from src.core.models import Offer
from src.filters.results import FilterResult


class LanguageFilter:
  def __init__(self, idiomas_permitidos: list[str]) -> None:
    normalized = [lang.strip().upper() for lang in idiomas_permitidos if lang.strip()]
    if not normalized:
      raise ValueError('filtros.idiomas_permitidos no puede estar vacio')
    self.idiomas_permitidos = set(normalized)
    self.detector = LanguageDetectorBuilder.from_all_languages().build()

  def apply(self, offer: Offer) -> FilterResult:
    text = offer.descripcion_md.strip()
    if not text:
      return FilterResult(pasa=False, motivo='empty_text', idioma_detectado=None)

    detected = self.detector.detect_language_of(text)
    if detected is None or detected.iso_code_639_1 is None:
      return FilterResult(pasa=False, motivo='language_not_detected', idioma_detectado=None)

    code = detected.iso_code_639_1.name.upper()
    if code in self.idiomas_permitidos:
      return FilterResult(pasa=True, motivo='allowed_language', idioma_detectado=code)
    return FilterResult(pasa=False, motivo='language_not_allowed', idioma_detectado=code)

