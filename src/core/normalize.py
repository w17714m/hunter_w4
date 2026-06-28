from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.core.models import Offer


SourceName = Literal['elempleo', 'linkedin', 'computrabajo']


def canonicalize_url(url: str) -> str:
  raw = (url or '').strip()
  if not raw:
    raise ValueError('La oferta debe tener una URL valida para normalizar')
  if not raw.lower().startswith(('http://', 'https://')):
    raw = f'https://{raw.lstrip("/")}'

  parsed = urlparse(raw)
  if not parsed.netloc:
    raise ValueError('La oferta debe tener una URL valida para normalizar')

  filtered_query = [
    (k, v)
    for k, v in parse_qsl(parsed.query, keep_blank_values=True)
    if not k.lower().startswith('utm_')
  ]
  normalized_query = urlencode(filtered_query, doseq=True)

  cleaned = parsed._replace(
    scheme=(parsed.scheme or 'https').lower(),
    netloc=parsed.netloc.lower(),
    path=parsed.path.rstrip('/'),
    params='',
    query=normalized_query,
    fragment='',
  )
  return urlunparse(cleaned)


def stable_offer_id(source: SourceName, canonical_url: str) -> str:
  token = f'{source}|{canonical_url}'.encode('utf-8')
  return sha256(token).hexdigest()


def _coerce_posted_date(value: Any) -> date | None:
  if value is None:
    return None
  if isinstance(value, date) and not isinstance(value, datetime):
    return value
  if isinstance(value, datetime):
    return value.date()
  if isinstance(value, str):
    stripped = value.strip()
    if not stripped:
      return None
    try:
      return date.fromisoformat(stripped)
    except ValueError:
      try:
        return datetime.fromisoformat(stripped).date()
      except ValueError:
        return None
  return None


@dataclass(slots=True)
class OfferNormalizer:
  def normalize(self, source: SourceName, raw_offer: dict[str, Any]) -> Offer:
    canonical_url = canonicalize_url(
      self._pick_first(raw_offer, 'url', 'link', 'job_url', 'oferta_url') or '',
    )
    offer_id = stable_offer_id(source, canonical_url)

    titulo = self._pick_first(raw_offer, 'titulo', 'title', 'cargo', 'position')
    if not titulo:
      raise ValueError('La oferta no contiene titulo/cargo')

    descripcion_md = self._pick_first(raw_offer, 'descripcion_md')
    if descripcion_md is None:
      raise ValueError('La oferta no contiene descripcion_md')

    if source == 'elempleo':
      empresa = self._pick_first(raw_offer, 'empresa', 'company', 'company_name')
      ubicacion = self._pick_first(raw_offer, 'ubicacion', 'ciudad', 'location')
    elif source == 'computrabajo':
      empresa = self._pick_first(raw_offer, 'empresa', 'company', 'company_name')
      ubicacion = self._pick_first(raw_offer, 'ubicacion', 'location')
    else:  # linkedin
      empresa = self._pick_first(raw_offer, 'empresa', 'company', 'company_name')
      ubicacion = self._pick_first(raw_offer, 'ubicacion', 'location')

    posted_date = _coerce_posted_date(
      self._pick_first(raw_offer, 'posted_date', 'fecha_publicacion', 'published_at'),
    ) or date.today()

    return Offer(
      id=offer_id,
      fuente=source,
      url=canonical_url,
      titulo=titulo.strip(),
      empresa=empresa.strip() if isinstance(empresa, str) and empresa.strip() else None,
      ubicacion=ubicacion.strip() if isinstance(ubicacion, str) and ubicacion.strip() else None,
      posted_date=posted_date,
      descripcion_md=descripcion_md,
    )

  @staticmethod
  def _pick_first(raw_offer: dict[str, Any], *keys: str) -> Any:
    for key in keys:
      if key in raw_offer and raw_offer[key] is not None:
        return raw_offer[key]
    return None
