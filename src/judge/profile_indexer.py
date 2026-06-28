from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from src.embeddings.vector_store import LanceDbStore

PROFILE_NAMESPACE = 'perfil'
_SECTION_RE = re.compile(r'^#{1,3}\s+.+', re.MULTILINE)


def _split_sections(text: str) -> list[tuple[str, str]]:
  """Divide el texto Markdown en secciones por encabezados H1-H3.

  Retorna lista de (id_fragmento, texto_fragmento).
  Si no hay encabezados, retorna el texto completo como un solo fragmento.
  """
  boundaries = [m.start() for m in _SECTION_RE.finditer(text)]

  if not boundaries:
    return [('section_0', text.strip())]

  fragments: list[tuple[str, str]] = []
  for i, start in enumerate(boundaries):
    end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
    chunk = text[start:end].strip()
    if chunk:
      fragments.append((f'section_{i}', chunk))

  return fragments


class ProfileIndexer:
  """Divide config/profile.md en secciones y las indexa en LanceDB.

  Namespace fijo: 'perfil'. Se ejecuta manualmente cada vez que el usuario
  edita su perfil. Reemplaza todos los fragmentos existentes en el namespace.
  """

  def __init__(self, store: LanceDbStore) -> None:
    self.store = store

  def index(self, profile_text: str) -> int:
    """Indexa el perfil. Retorna el número de fragmentos almacenados."""
    fragments = _split_sections(profile_text)
    self.store.upsert_batch(PROFILE_NAMESPACE, fragments)
    return len(fragments)
