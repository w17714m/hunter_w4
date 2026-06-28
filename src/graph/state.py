from __future__ import annotations

from typing import Any, TypedDict

from src.core.models import Offer


class PipelineState(TypedDict):
    # ── Entrada (requerida, siempre presente) ─────────────────────────────
    raw: dict[str, Any]
    source: str

    # ── Construido en node_normalizar ─────────────────────────────────────
    offer: Offer | None          # None hasta que normalizar corra

    # ── Enriquecido en node_similitud ─────────────────────────────────────
    similitud: float | None      # None si perfil no indexado

    # ── Control de flujo ──────────────────────────────────────────────────
    # "duplicate" y "error_normalizacion" son internos al grafo; nunca van a save_state
    estado_final: str
    descartada: bool
