"""Tests unitarios para Bug N — get_config cacheada no recarga en scheduler."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from src.config.loaders import clear_config_cache, get_config


def test_clear_config_cache_allows_reload() -> None:
    """clear_config_cache() debe permitir que la siguiente llamada recargue desde disco."""
    with patch('src.config.loaders.SettingsLoader.load', return_value=MagicMock()) as mock_load:
        get_config.cache_clear()
        get_config()
        get_config()
        assert mock_load.call_count == 1   # second call used the cache

        clear_config_cache()
        get_config()
        assert mock_load.call_count == 2   # reloaded after clear


def test_get_config_is_cached_without_clear() -> None:
    """Sin clear, llamadas consecutivas con mismos args devuelven el mismo objeto."""
    with patch('src.config.loaders.SettingsLoader.load', return_value=MagicMock()) as mock_load:
        get_config.cache_clear()
        first = get_config()
        second = get_config()
        assert first is second
        assert mock_load.call_count == 1


def test_scheduler_clears_cache_before_each_run() -> None:
    """Bug N: _run_scheduler debe llamar clear_config_cache() en cada ciclo."""
    from src import runner
    source = inspect.getsource(runner._run_scheduler)
    assert 'clear_config_cache' in source, (
        "Bug N no corregido: _run_scheduler no llama clear_config_cache() "
        "antes de run_once(). La config no se recarga entre ciclos del scheduler."
    )
