"""Global pytest configuration for the Job Hunter project.

Flag --run-integration: enables integration tests that require
external services (Ollama, Telegram, Playwright, internet).

Without the flag, all tests marked with @pytest.mark.integration
are skipped automatically.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        '--run-integration',
        action='store_true',
        default=False,
        help='Run integration tests against real external services.',
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        'markers',
        'integration: tests that require external services. Enable with --run-integration.',
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption('--run-integration'):
        return  # nothing to skip

    skip_integration = pytest.mark.skip(
        reason='Integration test skipped. Use --run-integration to run.'
    )
    for item in items:
        if 'integration' in item.keywords:
            item.add_marker(skip_integration)
