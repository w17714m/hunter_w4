"""Smoke test — pipeline completo con config real, 1 oferta por fuente.

Corre el flujo de punta a punta: scraping → normalización → filtros → embeddings
→ juez LLM → notificación/exportación, usando settings.yaml y profile.md reales.

Para debuggear en PyCharm: click derecho sobre este archivo → Debug.
Run Configuration:
  Interpreter  : .venv\Scripts\python.exe  (directo, sin uv)
  Working dir  : D:\Projects_Portfolio\Hunter_w4
"""
from __future__ import annotations

import asyncio

from src.runner import run_trial


def test_pipeline_smoke_trial() -> None:
    """Ejecuta run_trial() — 1 oferta por fuente por el cascade completo."""
    asyncio.run(run_trial())
