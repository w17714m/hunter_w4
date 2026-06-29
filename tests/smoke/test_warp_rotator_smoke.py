"""Smoke tests for WarpRotator — hit the real warp-cli binary, no mocks.

Run with:
    uv run pytest tests/smoke/test_warp_rotator_smoke.py -v -s
"""
from __future__ import annotations

import asyncio

import pytest

from src.stealth.warp_rotator import WarpRotator


# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------

def test_warp_cli_is_available() -> None:
    """warp-cli must be found on PATH before any rotation test can run."""
    rotator = WarpRotator(enabled=True)
    available = asyncio.run(rotator._is_available())
    if not available:
        pytest.skip('warp-cli not found on PATH — install Cloudflare WARP and ensure warp-cli is on PATH')
    assert available is True


# ---------------------------------------------------------------------------
# IP before / after
# ---------------------------------------------------------------------------

def test_get_current_ip_returns_string() -> None:
    """_get_current_ip must return a non-empty string when WARP is connected."""
    rotator = WarpRotator(enabled=True)
    available = asyncio.run(rotator._is_available())
    if not available:
        pytest.skip('warp-cli not available')

    ip = asyncio.run(rotator._get_current_ip())
    assert ip is not None, '_get_current_ip returned None — check internet connectivity'
    assert len(ip) > 0
    # Basic sanity: must look like an IPv4 or IPv6 address (contains digits and dots/colons)
    assert any(c.isdigit() for c in ip), f'IP does not look valid: {ip!r}'


# ---------------------------------------------------------------------------
# Full rotation cycle
# ---------------------------------------------------------------------------

def test_rotate_returns_true_and_changes_ip() -> None:
    """rotate() must complete successfully and the IP must differ before/after.

    Skipped if warp-cli is not available.
    The test is allowed to see the same IP if Cloudflare assigns the same exit node
    by chance — we only assert that rotate() returned True, not that the IP changed,
    because the pool assignment is outside our control.  The IPs are printed so the
    tester can verify manually.
    """
    rotator = WarpRotator(enabled=True)
    available = asyncio.run(rotator._is_available())
    if not available:
        pytest.skip('warp-cli not available')

    ip_before = asyncio.run(rotator._get_current_ip())
    print(f'\n  IP before rotation : {ip_before}')

    success = asyncio.run(rotator.rotate())

    ip_after = asyncio.run(rotator._get_current_ip())
    print(f'  IP after  rotation : {ip_after}')

    assert success is True, 'rotate() returned False — check warp-cli output'

    if ip_before and ip_after and ip_before == ip_after:
        # Not a hard failure — Cloudflare may assign the same exit node
        print('  Note: IP did not change (Cloudflare assigned the same exit node)')
