"""Configuración global de pytest para el proyecto Job Hunter.

Flag --run-integration: activa los tests de integración que requieren
servicios externos (Ollama, Telegram, Playwright, internet).

Sin el flag, todos los tests marcados con @pytest.mark.integration
se saltan automáticamente.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        '--run-integration',
        action='store_true',
        default=False,
        help='Ejecutar tests de integración contra servicios externos reales.',
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        'markers',
        'integration: tests que requieren servicios externos. Activar con --run-integration.',
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption('--run-integration'):
        return  # no saltar nada

    skip_integration = pytest.mark.skip(
        reason='Test de integración omitido. Usar --run-integration para ejecutar.'
    )
    for item in items:
        if 'integration' in item.keywords:
            item.add_marker(skip_integration)
