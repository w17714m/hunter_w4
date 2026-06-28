from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from src.embeddings.vector_store import LanceDbStore

PROFILE_NAMESPACE = 'perfil'
_SECTION_RE = re.compile(r'^#{1,3}\s+.+', re.MULTILINE)


def _split_sections(text: str) -> list[tuple[str, str]]:
  """Split Markdown text into sections by H1-H3 headings.

  Returns a list of (fragment_id, fragment_text).
  If there are no headings, returns the full text as a single fragment.
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
  """Split config/profile.md into sections and index them in LanceDB.

  Fixed namespace: 'perfil'. Run manually each time the user edits their profile.
  Replaces all existing fragments in the namespace.
  """

  def __init__(self, store: LanceDbStore) -> None:
    self.store = store

  def index(self, profile_text: str) -> int:
    """Index the profile. Returns the number of stored fragments."""
    fragments = _split_sections(profile_text)
    self.store.upsert_batch(PROFILE_NAMESPACE, fragments)
    return len(fragments)
