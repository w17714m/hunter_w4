from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import lancedb
import pyarrow as pa

if TYPE_CHECKING:
  from src.embeddings.ollama_embedder import OllamaEmbedder


# Schema Arrow para la tabla de vectores.
# embedding: vector de dimensión dinámica (se infiere al crear la tabla).
# id y text son los únicos campos obligatorios para todas las tablas.
_BASE_FIELDS = [
  pa.field('id', pa.string()),
  pa.field('text', pa.string()),
]


def _make_schema(dim: int) -> pa.Schema:
  return pa.schema([
    *_BASE_FIELDS,
    pa.field('embedding', pa.list_(pa.float32(), dim)),
  ])


class LanceDbStore:
  """Almacén vectorial basado en LanceDB.

  Cada namespace es una tabla independiente dentro del mismo directorio.
  Soporta upsert por id y búsqueda por similitud coseno.
  """

  def __init__(self, path: str, embedder: OllamaEmbedder) -> None:
    self.path = Path(path)
    self.path.mkdir(parents=True, exist_ok=True)
    self.embedder = embedder
    self._db = lancedb.connect(str(self.path))
    self._tables: dict[str, lancedb.table.Table] = {}

  # ------------------------------------------------------------------
  # Escritura
  # ------------------------------------------------------------------

  def upsert(self, namespace: str, doc_id: str, text: str) -> None:
    """Genera el embedding de `text` y lo almacena en el namespace dado.

    Si ya existe un registro con el mismo `id`, lo reemplaza.
    """
    vector = self.embedder.embed(text)
    dim = len(vector)
    table = self._get_or_create_table(namespace, dim)

    # LanceDB no tiene upsert nativo: borrar el id existente y re-insertar.
    try:
      table.delete(f"id = '{doc_id}'")
    except Exception:
      pass

    table.add([{
      'id': doc_id,
      'text': text,
      'embedding': vector,
    }])

  def upsert_batch(self, namespace: str, docs: list[tuple[str, str]]) -> None:
    """Upsert de múltiples (id, text) con una sola llamada batch al embedder."""
    if not docs:
      return
    ids, texts = zip(*docs)
    vectors = self.embedder.embed_batch(list(texts))
    dim = len(vectors[0])
    table = self._get_or_create_table(namespace, dim)

    for doc_id in ids:
      try:
        table.delete(f"id = '{doc_id}'")
      except Exception:
        pass

    table.add([
      {'id': doc_id, 'text': text, 'embedding': vec}
      for doc_id, text, vec in zip(ids, texts, vectors)
    ])

  # ------------------------------------------------------------------
  # Lectura
  # ------------------------------------------------------------------

  def search(
    self,
    namespace: str,
    query_text: str,
    top_k: int = 10,
  ) -> list[dict[str, object]]:
    """Busca los `top_k` documentos más similares al texto de consulta.

    Devuelve lista de dicts con keys: id, text, score (distancia coseno, menor = más similar).
    Devuelve [] si el namespace no existe todavía.
    """
    if namespace not in self._db.list_tables().tables:
      return []

    table = self._db.open_table(namespace)
    query_vec = self.embedder.embed(query_text)

    results = (
      table.search(query_vec)
      .metric('cosine')
      .limit(top_k)
      .select(['id', 'text'])
      .to_list()
    )

    return [
      {
        'id': row['id'],
        'text': row['text'],
        'score': float(row.get('_distance', row.get('score', 0.0))),
      }
      for row in results
    ]

  def exists(self, namespace: str, doc_id: str) -> bool:
    """Comprueba si un documento con ese id ya está indexado."""
    if namespace not in self._db.list_tables().tables:
      return False
    table = self._db.open_table(namespace)
    rows = table.search().where(f"id = '{doc_id}'").limit(1).to_list()
    return len(rows) > 0

  def count(self, namespace: str) -> int:
    """Número de documentos en el namespace. 0 si no existe."""
    if namespace not in self._db.list_tables().tables:
      return 0
    return self._db.open_table(namespace).count_rows()

  # ------------------------------------------------------------------
  # Interno
  # ------------------------------------------------------------------

  def _get_or_create_table(self, namespace: str, dim: int) -> lancedb.table.Table:
    if namespace in self._tables:
      return self._tables[namespace]

    if namespace in self._db.list_tables().tables:
      table = self._db.open_table(namespace)
    else:
      schema = _make_schema(dim)
      table = self._db.create_table(namespace, schema=schema)

    self._tables[namespace] = table
    return table
