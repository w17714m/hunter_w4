from __future__ import annotations

from pydantic import BaseModel


class FilterResult(BaseModel):
  pasa: bool
  motivo: str
  idioma_detectado: str | None = None

