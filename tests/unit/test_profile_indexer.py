from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from src.judge.profile_indexer import ProfileIndexer, _split_sections


# ---------------------------------------------------------------------------
# _split_sections
# ---------------------------------------------------------------------------

def test_split_no_headers():
  text = 'Solo texto plano sin encabezados.'
  fragments = _split_sections(text)
  assert len(fragments) == 1
  frag_id, frag_text = fragments[0]
  assert frag_id == 'section_0'
  assert 'Solo texto' in frag_text


def test_split_single_header():
  text = '# Experiencia\n\nTrabajé en Python por 5 años.'
  fragments = _split_sections(text)
  assert len(fragments) == 1
  assert '# Experiencia' in fragments[0][1]
  assert 'Python' in fragments[0][1]


def test_split_multiple_headers():
  text = (
    '# Experiencia\n\nPython, FastAPI.\n\n'
    '## Skills\n\nDocker, K8s.\n\n'
    '### Preferencias\n\nRemoto.'
  )
  fragments = _split_sections(text)
  assert len(fragments) == 3
  ids = [f[0] for f in fragments]
  assert ids == ['section_0', 'section_1', 'section_2']
  assert 'Experiencia' in fragments[0][1]
  assert 'Skills' in fragments[1][1]
  assert 'Preferencias' in fragments[2][1]


def test_split_skips_empty_chunks():
  # Header seguido inmediatamente de otro header (sin texto entre ellos)
  text = '# A\n# B\nContenido B'
  fragments = _split_sections(text)
  # Primer chunk es solo '# A', que strip() deja como '# A' → no vacío
  # Segundo chunk es '# B\nContenido B'
  assert len(fragments) == 2


# ---------------------------------------------------------------------------
# ProfileIndexer
# ---------------------------------------------------------------------------

def _make_store_mock():
  store = MagicMock()
  return store


def test_indexer_calls_upsert_batch():
  store = _make_store_mock()
  indexer = ProfileIndexer(store)
  profile_text = '# Experiencia\n\nPython.\n\n## Skills\n\nDocker.'

  count = indexer.index(profile_text)

  assert count == 2
  store.upsert_batch.assert_called_once()
  namespace_arg, docs_arg = store.upsert_batch.call_args.args
  assert namespace_arg == 'perfil'
  assert len(docs_arg) == 2


def test_indexer_single_fragment_no_headers():
  store = _make_store_mock()
  indexer = ProfileIndexer(store)

  count = indexer.index('Texto sin encabezados')

  assert count == 1
  store.upsert_batch.assert_called_once()


def test_indexer_returns_fragment_count():
  store = _make_store_mock()
  indexer = ProfileIndexer(store)
  text = '# A\n\nA.\n\n# B\n\nB.\n\n# C\n\nC.'

  assert indexer.index(text) == 3
