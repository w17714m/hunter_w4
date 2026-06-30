from datetime import date

import pytest

from src.core.db import SQLiteOfferRepository
from src.core.models import MatchVerdict, Offer, SkillMatch


def build_offer(offer_id: str = 'offer-1') -> Offer:
  return Offer(
    id=offer_id,
    fuente='linkedin',
    url='https://linkedin.com/jobs/view/1',
    titulo='Python Engineer',
    empresa='ACME',
    ubicacion='Remote',
    posted_date=date(2026, 6, 22),
    descripcion_md='## Oferta\n\nPython y FastAPI',
  )


def test_sqlite_upsert_and_duplicate_detection(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer = build_offer()

  repo.upsert(offer)
  assert repo.is_duplicate(offer.id) is True

  updated = offer.model_copy(update={'titulo': 'Senior Python Engineer'})
  repo.upsert(updated)

  recent = repo.fetch_recent(days=1)
  assert len(recent) == 1
  assert recent[0].titulo == 'Senior Python Engineer'


def test_save_state_updates_terminal_fields(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer = build_offer()
  repo.upsert(offer)

  skill_match = SkillMatch(
    skills_encontrados=['Python', 'FastAPI'],
    skills_faltantes=['AWS'],
    fraccion=2 / 3,
    pasa=True,
  )
  verdict = MatchVerdict(
    score=0.86,
    apto=True,
    razon='Buen encaje para backend',
    puntos_favor=['Experiencia Python', 'FastAPI'],
    puntos_contra=['No evidencia AWS'],
  )

  repo.save_state(
    offer_id=offer.id,
    estado='matched',
    skill_match=skill_match,
    similitud=0.88,
    veredicto=verdict,
  )

  recent = repo.fetch_recent(days=1)
  assert len(recent) == 1
  stored = recent[0]
  assert stored.estado == 'matched'
  assert stored.skill_match is not None and stored.skill_match.pasa is True
  assert stored.similitud == pytest.approx(0.88)
  assert stored.veredicto is not None and stored.veredicto.apto is True


def test_count_by_status_returns_metrics(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer_1 = build_offer('offer-1')
  offer_2 = build_offer('offer-2').model_copy(update={'estado': 'old'})

  repo.upsert(offer_1)
  repo.upsert(offer_2)
  repo.save_state(offer_1.id, 'low_sim')

  counts = repo.count_by_status()
  assert counts == {'low_sim': 1, 'old': 1}


def test_has_any_returns_existing_ids(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer = build_offer('offer-seen')
  repo.upsert(offer)

  result = repo.has_any([offer.id, 'id-desconocido'])

  assert offer.id in result
  assert 'id-desconocido' not in result


def test_has_any_empty_input_returns_empty_set(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  assert repo.has_any([]) == set()


def test_has_any_all_unknown_returns_empty_set(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  result = repo.has_any(['no-existe-1', 'no-existe-2'])
  assert result == set()


def test_has_any_multiple_existing_ids(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer_a = build_offer('offer-a')
  offer_b = build_offer('offer-b').model_copy(update={'url': 'https://linkedin.com/jobs/view/2'})
  repo.upsert(offer_a)
  repo.upsert(offer_b)

  result = repo.has_any([offer_a.id, offer_b.id, 'no-existe'])

  assert offer_a.id in result
  assert offer_b.id in result
  assert 'no-existe' not in result


# ---------------------------------------------------------------------------
# company_blacklist
# ---------------------------------------------------------------------------

def test_blacklist_add_and_check(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  repo.add_to_blacklist('CV Harvesters S.A.', reason='Vende datos de candidatos')
  assert repo.is_blacklisted('CV Harvesters S.A.') is True
  assert repo.is_blacklisted('Empresa Legítima') is False


def test_blacklist_upsert_updates_reason(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  repo.add_to_blacklist('Spamco', reason='Razón inicial')
  repo.add_to_blacklist('Spamco', reason='Razón actualizada')
  # Must not raise and must return still blacklisted
  assert repo.is_blacklisted('Spamco') is True


def test_blacklist_empty_reason_allowed(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  repo.add_to_blacklist('NoReasonCorp')
  assert repo.is_blacklisted('NoReasonCorp') is True


def test_blacklist_case_sensitive(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  repo.add_to_blacklist('acme')
  # SQLite TEXT PRIMARY KEY is case-sensitive by default
  assert repo.is_blacklisted('ACME') is False


# ---------------------------------------------------------------------------
# update_empresa
# ---------------------------------------------------------------------------

def test_update_empresa_fills_null(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer = build_offer('offer-null-empresa').model_copy(update={'empresa': None})
  repo.upsert(offer)

  repo.update_empresa('offer-null-empresa', 'Empresa Detectada')

  recent = repo.fetch_recent(days=1)
  assert recent[0].empresa == 'Empresa Detectada'


def test_update_empresa_does_not_overwrite_existing(tmp_path) -> None:
  repo = SQLiteOfferRepository(str(tmp_path / 'jobs.db'))
  offer = build_offer('offer-has-empresa')  # empresa='ACME' from build_offer
  repo.upsert(offer)

  repo.update_empresa('offer-has-empresa', 'Empresa Nueva')

  recent = repo.fetch_recent(days=1)
  # empresa was 'ACME', not NULL — must not be overwritten
  assert recent[0].empresa == 'ACME'

