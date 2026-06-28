"""Integration test — real Ollama + real LanceDB in a temporary directory.

Run manually:
    uv run pytest tests/integration/test_embeddings_integration.py -v -s

Requires:
  - Ollama running on WSL with nomic-embed-text available.
  - OLLAMA_BASE_URL pointing to the WSL host (default http://localhost:11434).
"""
from __future__ import annotations

import os
import tempfile

import pytest

from src.embeddings.ollama_embedder import OllamaEmbedder, OllamaEmbedderError
from src.embeddings.vector_store import LanceDbStore


OLLAMA_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
EMBED_MODEL = os.getenv('EMBED_MODEL', 'nomic-embed-text')


@pytest.mark.integration
def test_ollama_embedder_real_vector_has_dimension() -> None:
  embedder = OllamaEmbedder(base_url=OLLAMA_URL, model=EMBED_MODEL)
  vec = embedder.embed('Python developer con experiencia en FastAPI y AWS')
  assert isinstance(vec, list)
  assert len(vec) > 0
  assert all(isinstance(v, float) for v in vec)


@pytest.mark.integration
def test_ollama_embedder_different_texts_give_different_vectors() -> None:
  embedder = OllamaEmbedder(base_url=OLLAMA_URL, model=EMBED_MODEL)
  vec_a = embedder.embed('Python backend developer')
  vec_b = embedder.embed('Conductor de camión')
  assert vec_a != vec_b


@pytest.mark.integration
def test_lancedb_upsert_and_search_real_embeddings() -> None:
  embedder = OllamaEmbedder(base_url=OLLAMA_URL, model=EMBED_MODEL)
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=embedder)

    docs = [
      ('id-python', 'Python developer senior con FastAPI, Docker y AWS. Experiencia en microservicios.'),
      ('id-java', 'Java backend engineer Spring Boot Kubernetes. Arquitectura hexagonal.'),
      ('id-frontend', 'React developer frontend JavaScript TypeScript. Diseño de interfaces.'),
    ]
    store.upsert_batch('ofertas', docs)
    assert store.count('ofertas') == 3

    # The Python search must rank id-python highest
    results = store.search('ofertas', 'python microservices developer', top_k=3)
    assert len(results) == 3
    assert results[0]['id'] == 'id-python', (
      f'Expected id-python first, got: {[r["id"] for r in results]}'
    )


@pytest.mark.integration
def test_lancedb_profile_namespace_persists_across_instances() -> None:
  """The profile index persists on disk and can be queried from a second instance."""
  embedder = OllamaEmbedder(base_url=OLLAMA_URL, model=EMBED_MODEL)
  with tempfile.TemporaryDirectory() as tmp:
    store1 = LanceDbStore(path=tmp, embedder=embedder)
    store1.upsert('perfil', 'perfil-principal', 'Soy un desarrollador Python con 5 años de experiencia.')

    # second instance pointing at the same directory
    store2 = LanceDbStore(path=tmp, embedder=embedder)
    assert store2.count('perfil') == 1
    assert store2.exists('perfil', 'perfil-principal') is True

    results = store2.search('perfil', 'desarrollador python', top_k=1)
    assert results[0]['id'] == 'perfil-principal'
