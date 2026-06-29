"""Unit tests for VisitBudget."""
from __future__ import annotations

import pytest

from src.core.visit_budget import VisitBudget, VisitBudgetProtocol


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_budget_starts_with_full_remaining() -> None:
    assert VisitBudget(150).remaining() == 150


def test_budget_starts_not_exhausted() -> None:
    assert VisitBudget(150).exhausted() is False


def test_budget_starts_consumed_zero() -> None:
    assert VisitBudget(150).consumed() == 0


def test_budget_zero_limit_is_immediately_exhausted() -> None:
    assert VisitBudget(0).exhausted() is True


def test_budget_zero_limit_remaining_is_zero() -> None:
    assert VisitBudget(0).remaining() == 0


def test_budget_negative_limit_raises_value_error() -> None:
    with pytest.raises(ValueError):
        VisitBudget(-1)


# ---------------------------------------------------------------------------
# consume()
# ---------------------------------------------------------------------------

def test_consume_returns_true_when_budget_available() -> None:
    assert VisitBudget(10).consume() is True


def test_consume_decrements_remaining() -> None:
    b = VisitBudget(10)
    b.consume()
    assert b.remaining() == 9


def test_consume_increments_consumed() -> None:
    b = VisitBudget(10)
    b.consume()
    assert b.consumed() == 1


def test_consume_returns_false_when_exhausted() -> None:
    b = VisitBudget(2)
    b.consume()
    b.consume()
    assert b.consume() is False


def test_consume_on_zero_budget_returns_false_immediately() -> None:
    assert VisitBudget(0).consume() is False


def test_consume_does_not_go_below_zero() -> None:
    b = VisitBudget(1)
    b.consume()
    b.consume()  # already exhausted
    assert b.remaining() == 0
    assert b.consumed() == 1  # does not exceed the limit


def test_consume_clamps_to_limit() -> None:
    b = VisitBudget(3)
    b.consume()
    b.consume()
    b.consume()
    # consuming beyond the limit does not break the count
    b.consume()
    assert b.consumed() == 3
    assert b.remaining() == 0


def test_consume_at_exact_limit_exhausts() -> None:
    b = VisitBudget(5)
    for _ in range(5):
        b.consume()
    assert b.exhausted() is True
    assert b.remaining() == 0


# ---------------------------------------------------------------------------
# exhausted()
# ---------------------------------------------------------------------------

def test_exhausted_false_with_remaining() -> None:
    b = VisitBudget(5)
    b.consume()
    assert b.exhausted() is False


def test_exhausted_true_after_all_consumed() -> None:
    b = VisitBudget(2)
    b.consume()
    b.consume()
    assert b.exhausted() is True


def test_exhausted_does_not_change_state() -> None:
    b = VisitBudget(5)
    b.exhausted()
    b.exhausted()
    assert b.remaining() == 5


# ---------------------------------------------------------------------------
# Realistic scenario
# ---------------------------------------------------------------------------

def test_budget_sequence_matches_expected_scenario() -> None:
    """Search 1: 80 visits. Search 2: attempts 90, gets only 70. Search 3: exhausted."""
    budget = VisitBudget(limit=150)

    for _ in range(80):
        assert budget.consume() is True
    assert budget.remaining() == 70
    assert budget.exhausted() is False

    consumed_in_search2 = 0
    for _ in range(90):
        if not budget.consume():
            break
        consumed_in_search2 += 1

    assert consumed_in_search2 == 70
    assert budget.exhausted() is True
    assert budget.remaining() == 0

    assert budget.consume() is False


# ---------------------------------------------------------------------------
# Protocol check
# ---------------------------------------------------------------------------

def test_visit_budget_implements_protocol() -> None:
    budget = VisitBudget(limit=10)
    assert isinstance(budget, VisitBudgetProtocol)


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

def test_repr_contains_consumed_and_limit() -> None:
    b = VisitBudget(50)
    b.consume()
    r = repr(b)
    assert 'consumed=1' in r
    assert 'limit=50' in r
