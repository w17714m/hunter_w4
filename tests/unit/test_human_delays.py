from __future__ import annotations

import asyncio

from src.stealth.human_delays import between_requests_delay, jitter, page_load_delay, typing_delay


# ---------------------------------------------------------------------------
# jitter
# ---------------------------------------------------------------------------

async def test_jitter_sleeps_within_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await jitter(1.0, 3.0)
    assert len(sleeps) == 1
    assert 1.0 <= sleeps[0] <= 3.0


async def test_jitter_zero_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await jitter(2.5, 2.5)
    assert sleeps[0] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# page_load_delay
# ---------------------------------------------------------------------------

async def test_page_load_delay_default_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await page_load_delay()
    assert len(sleeps) == 1
    assert 2.0 <= sleeps[0] <= 5.0


async def test_page_load_delay_custom_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await page_load_delay(min_s=0.1, max_s=0.2)
    assert 0.1 <= sleeps[0] <= 0.2


# ---------------------------------------------------------------------------
# between_requests_delay
# ---------------------------------------------------------------------------

async def test_between_requests_delay_default_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await between_requests_delay()
    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 2.0


# ---------------------------------------------------------------------------
# typing_delay
# ---------------------------------------------------------------------------

async def test_typing_delay_default_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await typing_delay()
    assert len(sleeps) == 1
    assert 0.05 <= sleeps[0] <= 0.15


async def test_typing_delay_custom_range(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)
    await typing_delay(min_s=0.01, max_s=0.02)
    assert 0.01 <= sleeps[0] <= 0.02


import pytest  # noqa: E402 — needed for pytest.approx used above
