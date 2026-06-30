from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.core.models import MatchVerdict, Offer, SkillMatch


class SQLiteOfferRepository:
  def __init__(self, db_path: str = 'data/jobs.db') -> None:
    self.db_path = Path(db_path)
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._ensure_schema()

  def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(str(self.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn

  def _ensure_schema(self) -> None:
    with self._connect() as conn:
      conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS offers (
          id TEXT PRIMARY KEY,
          fuente TEXT NOT NULL,
          url TEXT NOT NULL,
          titulo TEXT NOT NULL,
          empresa TEXT,
          ubicacion TEXT,
          posted_date TEXT,
          descripcion_md TEXT NOT NULL,
          estado TEXT NOT NULL,
          skill_match_json TEXT,
          skills_oferta_json TEXT,
          similitud REAL,
          veredicto_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        ''',
      )
      conn.execute('CREATE INDEX IF NOT EXISTS idx_offers_estado ON offers(estado)')
      conn.execute('CREATE INDEX IF NOT EXISTS idx_offers_updated_at ON offers(updated_at)')
      try:
        conn.execute('ALTER TABLE offers ADD COLUMN skills_oferta_json TEXT')
      except sqlite3.OperationalError:
        pass
      conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS kv_store (
          key        TEXT PRIMARY KEY,
          value      TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        ''',
      )

  def upsert(self, offer: Offer) -> None:
    now = datetime.now(UTC).isoformat()
    skill_match_json = offer.skill_match.model_dump_json() if offer.skill_match else None
    skills_oferta_json = (
      json.dumps(offer.skill_match.skills_oferta, ensure_ascii=False)
      if offer.skill_match and offer.skill_match.skills_oferta
      else None
    )
    veredicto_json = offer.veredicto.model_dump_json() if offer.veredicto else None

    with self._connect() as conn:
      conn.execute(
        '''
        INSERT INTO offers (
          id, fuente, url, titulo, empresa, ubicacion, posted_date, descripcion_md, estado,
          skill_match_json, skills_oferta_json, similitud, veredicto_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          fuente=excluded.fuente,
          url=excluded.url,
          titulo=excluded.titulo,
          empresa=excluded.empresa,
          ubicacion=excluded.ubicacion,
          posted_date=excluded.posted_date,
          descripcion_md=excluded.descripcion_md,
          estado=excluded.estado,
          skill_match_json=excluded.skill_match_json,
          skills_oferta_json=excluded.skills_oferta_json,
          similitud=excluded.similitud,
          veredicto_json=excluded.veredicto_json,
          updated_at=excluded.updated_at
        ''',
        (
          offer.id,
          offer.fuente,
          offer.url,
          offer.titulo,
          offer.empresa,
          offer.ubicacion,
          offer.posted_date.isoformat() if offer.posted_date else None,
          offer.descripcion_md,
          offer.estado,
          skill_match_json,
          skills_oferta_json,
          offer.similitud,
          veredicto_json,
          now,
          now,
        ),
      )

  def is_duplicate(self, offer_id: str) -> bool:
    with self._connect() as conn:
      row = conn.execute('SELECT 1 FROM offers WHERE id = ? LIMIT 1', (offer_id,)).fetchone()
    return row is not None

  def has_any(self, offer_ids: list[str]) -> set[str]:
    """Retorna el subconjunto de offer_ids que ya existen en la DB. Una sola query."""
    if not offer_ids:
      return set()
    # SQLite limits IN to 999 parameters; chunk just in case.
    result: set[str] = set()
    chunk_size = 500
    with self._connect() as conn:
      for i in range(0, len(offer_ids), chunk_size):
        chunk = offer_ids[i : i + chunk_size]
        placeholders = ','.join('?' * len(chunk))
        rows = conn.execute(
          f'SELECT id FROM offers WHERE id IN ({placeholders})',
          chunk,
        ).fetchall()
        result.update(str(row['id']) for row in rows)
    return result

  def save_state(
    self,
    offer_id: str,
    estado: str,
    skill_match: SkillMatch | None = None,
    similitud: float | None = None,
    veredicto: MatchVerdict | None = None,
  ) -> None:
    now = datetime.now(UTC).isoformat()
    skill_match_json = skill_match.model_dump_json() if skill_match else None
    skills_oferta_json = (
      json.dumps(skill_match.skills_oferta, ensure_ascii=False)
      if skill_match and skill_match.skills_oferta
      else None
    )
    veredicto_json = veredicto.model_dump_json() if veredicto else None

    with self._connect() as conn:
      cursor = conn.execute(
        '''
        UPDATE offers
        SET estado = ?,
            skill_match_json = ?,
            skills_oferta_json = ?,
            similitud = ?,
            veredicto_json = ?,
            updated_at = ?
        WHERE id = ?
        ''',
        (estado, skill_match_json, skills_oferta_json, similitud, veredicto_json, now, offer_id),
      )
      if cursor.rowcount == 0:
        raise ValueError(f'No existe oferta con id={offer_id}')

  def kv_get(self, key: str) -> str | None:
    with self._connect() as conn:
      row = conn.execute('SELECT value FROM kv_store WHERE key = ?', (key,)).fetchone()
    return str(row['value']) if row else None

  def kv_set(self, key: str, value: str) -> None:
    now = datetime.now(UTC).isoformat()
    with self._connect() as conn:
      conn.execute(
        'INSERT INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)'
        ' ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
        (key, value, now),
      )

  def fetch_recent(self, days: int) -> list[Offer]:
    if days < 0:
      raise ValueError('days debe ser >= 0')
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    with self._connect() as conn:
      rows = conn.execute(
        '''
        SELECT
          id, fuente, url, titulo, empresa, ubicacion, posted_date, descripcion_md, estado,
          skill_match_json, skills_oferta_json, similitud, veredicto_json
        FROM offers
        WHERE updated_at >= ?
        ORDER BY updated_at DESC
        ''',
        (cutoff,),
      ).fetchall()

    return [self._row_to_offer(row) for row in rows]

  def count_by_status(self) -> dict[str, int]:
    with self._connect() as conn:
      rows = conn.execute(
        '''
        SELECT estado, COUNT(*) AS total
        FROM offers
        GROUP BY estado
        ''',
      ).fetchall()
    return {str(row['estado']): int(row['total']) for row in rows}

  @staticmethod
  def _row_to_offer(row: sqlite3.Row) -> Offer:
    skill_match = None
    if row['skill_match_json']:
      data = json.loads(str(row['skill_match_json']))
      if 'skills_oferta_json' in row.keys() and row['skills_oferta_json'] and 'skills_oferta' not in data:
        data['skills_oferta'] = json.loads(str(row['skills_oferta_json']))
      skill_match = SkillMatch.model_validate(data)

    veredicto = None
    if row['veredicto_json']:
      veredicto = MatchVerdict.model_validate(json.loads(str(row['veredicto_json'])))

    return Offer(
      id=str(row['id']),
      fuente=str(row['fuente']),
      url=str(row['url']),
      titulo=str(row['titulo']),
      empresa=row['empresa'],
      ubicacion=row['ubicacion'],
      posted_date=datetime.fromisoformat(str(row['posted_date'])).date() if row['posted_date'] else None,
      descripcion_md=str(row['descripcion_md']),
      estado=str(row['estado']),
      skill_match=skill_match,
      similitud=row['similitud'],
      veredicto=veredicto,
    )
