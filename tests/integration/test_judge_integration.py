"""Integración: ProfileIndexer + OllamaJudge contra servicios reales.

Requiere:
  - Ollama corriendo en localhost:11434
  - Modelos disponibles: nomic-embed-text (embeddings), deepseek-r1:14b (juez)
  - LanceDB en data/test_lancedb_judge/

Marca: pytest -m integration
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.embeddings.ollama_embedder import OllamaEmbedder
from src.embeddings.vector_store import LanceDbStore
from src.judge.ollama_judge import OllamaJudge
from src.judge.profile_indexer import ProfileIndexer

pytestmark = pytest.mark.integration

TEST_DB_PATH = 'data/test_lancedb_judge'

PROFILE_TEXT = """\
# Perfil profesional

Soy desarrollador backend con 5 años de experiencia en Python, FastAPI y PostgreSQL.
Me especializo en APIs REST, arquitectura de microservicios y contenedores Docker.

## Stack principal

Python 3.10+, FastAPI, SQLAlchemy, PostgreSQL, Docker, Kubernetes.

## Rol objetivo

Busco posiciones de Backend Developer o Python Engineer, preferiblemente remoto.

## Exclusiones

No me interesan roles de frontend puro ni posiciones que requieran más de 50% de viajes.
"""

OFFER_MD = """\
## Backend Python Developer

**Empresa:** StartupTech
**Ubicación:** Remoto (Colombia)

### Descripción

Buscamos desarrollador Python con experiencia en FastAPI y PostgreSQL.
El candidato trabajará en APIs REST para nuestra plataforma SaaS.

### Requisitos

- Python 3.9+
- FastAPI o Django REST Framework
- PostgreSQL
- Docker
- Conocimiento de microservicios
"""


@pytest.fixture(scope='module')
def db_path(tmp_path_factory):
  path = tmp_path_factory.mktemp('lancedb_judge')
  yield str(path)


@pytest.fixture(scope='module')
def embedder():
  return OllamaEmbedder(model='nomic-embed-text')


@pytest.fixture(scope='module')
def store(db_path, embedder):
  return LanceDbStore(path=db_path, embedder=embedder)


@pytest.fixture(scope='module')
def indexed_store(store):
  indexer = ProfileIndexer(store)
  indexer.index(PROFILE_TEXT)
  return store


def _make_offer() -> Offer:
  return Offer(
    id='judge-integ-001',
    fuente='elempleo',
    url='https://example.com/job/judge-test',
    titulo='Backend Python Developer',
    empresa='StartupTech',
    ubicacion='Remoto',
    posted_date=date(2024, 6, 1),
    descripcion_md=OFFER_MD,
    skill_match=SkillMatch(
      skills_encontrados=['Python', 'FastAPI', 'Docker'],
      skills_faltantes=['Kubernetes'],
      fraccion=0.75,
      pasa=True,
    ),
  )


def test_profile_indexer_stores_fragments(store):
  indexer = ProfileIndexer(store)
  count = indexer.index(PROFILE_TEXT)
  assert count >= 1
  assert store.count('perfil') >= 1


def test_judge_returns_valid_verdict(indexed_store):
  judge = OllamaJudge(
    store=indexed_store,
    model='deepseek-r1:14b',
    top_k_profile=3,
    truncar_chars=3000,
  )
  offer = _make_offer()
  verdict = judge.judge(offer)

  assert isinstance(verdict, MatchVerdict)
  assert 0.0 <= verdict.score <= 1.0
  assert isinstance(verdict.apto, bool)
  assert isinstance(verdict.razon, str) and verdict.razon
  assert isinstance(verdict.puntos_favor, list)
  assert isinstance(verdict.puntos_contra, list)


def test_judge_profile_fragments_retrieved(indexed_store):
  """El store recupera fragmentos relevantes del perfil para la oferta."""
  results = indexed_store.search(
    namespace='perfil',
    query_text=OFFER_MD,
    top_k=3,
  )
  assert len(results) >= 1
  texts = [r['text'] for r in results]
  assert any('Python' in t for t in texts)
