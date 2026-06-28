from __future__ import annotations

import asyncio
import random


async def jitter(min_s: float, max_s: float) -> None:
    """Sleep for a random duration between min_s and max_s seconds."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def page_load_delay(min_s: float = 2.0, max_s: float = 5.0) -> None:
    """Simulate human reading time between page navigations (default 2–5 s)."""
    await jitter(min_s, max_s)


async def between_requests_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Short pause between consecutive requests (default 0.5–2 s)."""
    await jitter(min_s, max_s)


async def typing_delay(min_s: float = 0.05, max_s: float = 0.15) -> None:
    """Pause that simulates typing a single character (default 0.05–0.15 s)."""
    await jitter(min_s, max_s)
