from __future__ import annotations

import re

from src.core.models import Offer
from src.core.models import SkillMatch
from src.filters.skill_extractor import LLMSkillExtractor


class SkillFilter:
  def __init__(
    self,
    required_skills: list[str],
    umbral_match: float,
    extractor: LLMSkillExtractor | None = None,
  ) -> None:
    if umbral_match < 0.0 or umbral_match > 1.0:
      raise ValueError('skills.umbral_match debe estar entre 0.0 y 1.0')
    self.required_skills = [skill.strip() for skill in required_skills if skill.strip()]
    self.umbral_match = umbral_match
    self.extractor = extractor

  def match(self, offer: Offer) -> SkillMatch:
    descripcion = offer.descripcion_md
    skills_oferta = self.extractor.extract(descripcion) if self.extractor else []

    if skills_oferta:
      # New logic: fraction = YAML skills covered / total skills the offer requires
      skills_encontrados = [
        s for s in self.required_skills
        if any(self._contains_whole_word(skill_oferta, s) for skill_oferta in skills_oferta)
      ]
      skills_faltantes = [
        s for s in skills_oferta
        if not any(self._contains_whole_word(s, req) for req in self.required_skills)
      ]
      fraccion = len(skills_encontrados) / len(skills_oferta)
    else:
      # Fallback: original logic — fraction over YAML list
      skills_encontrados = [
        skill for skill in self.required_skills
        if self._contains_whole_word(descripcion, skill)
      ]
      skills_faltantes = [
        skill for skill in self.required_skills if skill not in skills_encontrados
      ]
      fraccion = 1.0 if not self.required_skills else len(skills_encontrados) / len(self.required_skills)

    return SkillMatch(
      skills_encontrados=skills_encontrados,
      skills_faltantes=skills_faltantes,
      fraccion=fraccion,
      pasa=fraccion >= self.umbral_match,
      skills_oferta=skills_oferta,
    )

  def attach(self, offer: Offer) -> Offer:
    skill_match = self.match(offer)
    return offer.model_copy(update={'skill_match': skill_match})

  @staticmethod
  def _contains_whole_word(text: str, skill: str) -> bool:
    pattern = rf'(?<!\w){re.escape(skill)}(?!\w)'
    return re.search(pattern, text, flags=re.IGNORECASE) is not None
