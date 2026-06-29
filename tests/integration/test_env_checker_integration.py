"""Integration test: EnvironmentChecker against real services.

Run:
    uv run pytest tests/integration/test_env_checker_integration.py -v -m integration

Requires:
  - config/settings.yaml and .env configured
  - At least Ollama available for the test to be useful
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.setup_check import CheckResult, EnvironmentChecker
from src.config.loaders import get_config

pytestmark = pytest.mark.integration

VALID_ESTADOS = {'ok', 'warn', 'fail'}


@pytest.fixture(scope='module')
def checker():
    cfg = get_config()
    return EnvironmentChecker(cfg)


@pytest.mark.integration
def test_all_checks_return_valid_states(checker) -> None:
    results = checker.run_all()
    assert len(results) == 9
    for r in results:
        assert r.estado in VALID_ESTADOS, f'Invalid estado in check "{r.nombre}": {r.estado!r}'
        assert isinstance(r.mensaje, str) and r.mensaje
        assert r.accion is None or isinstance(r.accion, str)


@pytest.mark.integration
def test_skills_config_check_passes(checker) -> None:
    result = checker.check_skills_config()
    assert result.estado == 'ok', f'skills config failed: {result.mensaje}'


@pytest.mark.integration
def test_matches_dir_check_passes(checker) -> None:
    result = checker.check_matches_dir()
    assert result.estado == 'ok', f'matches dir failed: {result.mensaje}'


@pytest.mark.integration
def test_lancedb_check_passes(checker) -> None:
    result = checker.check_lancedb()
    assert result.estado == 'ok', f'LanceDB failed: {result.mensaje}'
