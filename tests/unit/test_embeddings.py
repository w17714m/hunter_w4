"""Tests unitarios para OllamaEmbedder y LanceDbStore (sin servicios externos)."""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.embeddings.ollama_embedder import OllamaEmbedder, OllamaEmbedderError
from src.embeddings.vector_store import LanceDbStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embedder(dim: int = 4) -> OllamaEmbedder:
  """Embedder mockeado que devuelve vectores unitarios deterministas."""
  embedder = MagicMock(spec=OllamaEmbedder)
  embedder.embed.side_effect = lambda text: [float(ord(text[0]) % (dim + 1)) / dim] * dim
  embedder.embed_batch.side_effect = lambda texts: [
    [float(ord(t[0]) % (dim + 1)) / dim] * dim for t in texts
  ]
  return embedder


# ---------------------------------------------------------------------------
# OllamaEmbedder — unit (HTTP mockeado)
# ---------------------------------------------------------------------------

def test_ollama_embedder_returns_vector() -> None:
  fake_vec = [0.1, 0.2, 0.3]
  with patch('httpx.post') as mock_post:
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {'embedding': fake_vec})
    embedder = OllamaEmbedder(base_url='http://localhost:11434', model='nomic-embed-text')
    result = embedder.embed('Python developer')
  assert result == fake_vec


def test_ollama_embedder_raises_on_http_error() -> None:
  with patch('httpx.post') as mock_post:
    mock_post.return_value = MagicMock(status_code=500, text='Internal error')
    embedder = OllamaEmbedder()
    with pytest.raises(OllamaEmbedderError, match='500'):
      embedder.embed('test')


def test_ollama_embedder_raises_on_missing_embedding_field() -> None:
  with patch('httpx.post') as mock_post:
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {'error': 'model not found'})
    embedder = OllamaEmbedder()
    with pytest.raises(OllamaEmbedderError, match='embedding'):
      embedder.embed('test')


def test_ollama_embedder_raises_on_connection_error() -> None:
  import httpx
  with patch('httpx.post', side_effect=httpx.ConnectError('refused')):
    embedder = OllamaEmbedder()
    with pytest.raises(OllamaEmbedderError, match='conectar'):
      embedder.embed('test')


def test_ollama_embedder_raises_on_empty_text() -> None:
  embedder = OllamaEmbedder()
  with pytest.raises(OllamaEmbedderError, match='vacío'):
    embedder.embed('   ')


def test_ollama_embedder_batch_calls_embed_per_text() -> None:
  fake_vec = [0.5, 0.5]
  with patch('httpx.post') as mock_post:
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {'embedding': fake_vec})
    embedder = OllamaEmbedder()
    results = embedder.embed_batch(['texto A', 'texto B'])
  assert len(results) == 2
  assert all(r == fake_vec for r in results)


# ---------------------------------------------------------------------------
# LanceDbStore — unit (embedder mockeado, LanceDB en directorio temporal)
# ---------------------------------------------------------------------------

def test_store_upsert_and_count() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    store.upsert('perfil', 'doc-1', 'Python developer con experiencia en FastAPI')
    assert store.count('perfil') == 1


def test_store_upsert_replaces_existing_id() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    store.upsert('perfil', 'doc-1', 'texto original')
    store.upsert('perfil', 'doc-1', 'texto actualizado')
    assert store.count('perfil') == 1


def test_store_upsert_batch_inserts_all() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    docs = [('id-1', 'Oferta A'), ('id-2', 'Oferta B'), ('id-3', 'Oferta C')]
    store.upsert_batch('ofertas', docs)
    assert store.count('ofertas') == 3


def test_store_exists_returns_true_after_upsert() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    store.upsert('ns', 'abc', 'algún texto')
    assert store.exists('ns', 'abc') is True


def test_store_exists_returns_false_before_upsert() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    assert store.exists('ns', 'no-existe') is False


def test_store_count_returns_zero_for_unknown_namespace() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    assert store.count('namespace-vacio') == 0


def test_store_search_returns_empty_for_unknown_namespace() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    results = store.search('vacio', 'cualquier texto', top_k=5)
    assert results == []


def test_store_search_returns_ranked_results() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    embedder = _fake_embedder(dim=8)
    store = LanceDbStore(path=tmp, embedder=embedder)
    store.upsert_batch('ofertas', [
      ('id-a', 'Python FastAPI backend'),
      ('id-b', 'Java Spring microservices'),
      ('id-c', 'React frontend JavaScript'),
    ])
    results = store.search('ofertas', 'Python developer', top_k=3)
    assert len(results) == 3
    assert all('id' in r and 'text' in r and 'score' in r for r in results)


def test_store_search_respects_top_k() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    docs = [(f'id-{i}', f'Texto {i}') for i in range(10)]
    store.upsert_batch('ns', docs)
    results = store.search('ns', 'query', top_k=3)
    assert len(results) <= 3


def test_store_namespaces_are_independent() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    store = LanceDbStore(path=tmp, embedder=_fake_embedder())
    store.upsert('ns-a', 'doc-1', 'texto en A')
    store.upsert('ns-b', 'doc-2', 'texto en B')
    assert store.count('ns-a') == 1
    assert store.count('ns-b') == 1
    assert store.exists('ns-a', 'doc-1') is True
    assert store.exists('ns-a', 'doc-2') is False
