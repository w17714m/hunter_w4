from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VisitBudgetProtocol(Protocol):
    def remaining(self) -> int: ...
    def consumed(self) -> int: ...
    def consume(self, n: int = 1) -> bool: ...
    def exhausted(self) -> bool: ...


class VisitBudget:
    """Detail-page visit counter with a per-cycle limit.

    Lifecycle: created in run_once() and discarded when it returns, so the
    per-cycle reset is automatic. None = no limit (run_trial).
    """

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError(f'limit must be >= 0, got: {limit}')
        self._limit = limit
        self._consumed = 0

    def remaining(self) -> int:
        return max(0, self._limit - self._consumed)

    def consumed(self) -> int:
        return self._consumed

    def consume(self, n: int = 1) -> bool:
        """Deduct n from the budget. Returns True if budget was available, False if exhausted."""
        if self._consumed >= self._limit:
            return False
        self._consumed = min(self._consumed + n, self._limit)
        return True

    def exhausted(self) -> bool:
        return self._consumed >= self._limit

    def __repr__(self) -> str:
        return f'VisitBudget(consumed={self._consumed}, limit={self._limit})'
