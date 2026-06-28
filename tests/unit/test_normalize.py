from datetime import date

from src.core.normalize import OfferNormalizer, canonicalize_url, stable_offer_id


def test_canonicalize_url_normalizes_host_and_removes_tracking_params() -> None:
  url = 'HTTPS://LinkedIn.com/jobs/view/123/?utm_source=x&foo=bar#fragment'
  assert canonicalize_url(url) == 'https://linkedin.com/jobs/view/123?foo=bar'


def test_stable_offer_id_is_idempotent() -> None:
  canonical_url = 'https://linkedin.com/jobs/view/123'
  value_1 = stable_offer_id('linkedin', canonical_url)
  value_2 = stable_offer_id('linkedin', canonical_url)
  assert value_1 == value_2


def test_normalize_elempleo_uses_defaults_and_keeps_markdown_verbatim() -> None:
  normalizer = OfferNormalizer()
  raw = {
    'url': 'www.elempleo.com/co/ofertas/1',
    'cargo': 'Backend Python',
    'empresa': 'ACME',
    'ciudad': 'Bogota',
    'descripcion_md': '## Oferta\n\nPython + FastAPI',
  }

  offer = normalizer.normalize('elempleo', raw)

  assert offer.fuente == 'elempleo'
  assert offer.url == 'https://www.elempleo.com/co/ofertas/1'
  assert offer.posted_date == date.today()
  assert offer.descripcion_md == raw['descripcion_md']


def test_normalize_linkedin_handles_alt_fields_and_iso_date() -> None:
  normalizer = OfferNormalizer()
  raw = {
    'link': 'linkedin.com/jobs/view/999/',
    'title': 'Python Engineer',
    'company_name': 'Globex',
    'location': 'Remote',
    'published_at': '2026-06-20T09:30:00',
    'descripcion_md': '*Python* y SQL',
  }

  offer = normalizer.normalize('linkedin', raw)

  assert offer.fuente == 'linkedin'
  assert offer.titulo == 'Python Engineer'
  assert offer.empresa == 'Globex'
  assert offer.ubicacion == 'Remote'
  assert offer.posted_date == date(2026, 6, 20)
  assert offer.descripcion_md == '*Python* y SQL'


def test_normalize_computrabajo_maps_all_fields() -> None:
  normalizer = OfferNormalizer()
  raw = {
    'url': 'https://co.computrabajo.com/ofertas-de-trabajo/python-dev-XYZABC',
    'titulo': 'Desarrollador Python',
    'empresa': 'DataCorp SAS',
    'ubicacion': 'Bogotá',
    'descripcion_md': '## Requisitos\n\n- Python 3.10+\n- FastAPI',
    'fuente': 'computrabajo',
    'scraped_at': '2026-06-27T10:00:00+00:00',
    'posted_date': '2026-06-27',
    'extraction_status': 'ok',
  }

  offer = normalizer.normalize('computrabajo', raw)

  assert offer.fuente == 'computrabajo'
  assert offer.titulo == 'Desarrollador Python'
  assert offer.empresa == 'DataCorp SAS'
  assert offer.ubicacion == 'Bogotá'
  assert offer.posted_date == date(2026, 6, 27)
  assert offer.descripcion_md == raw['descripcion_md']

