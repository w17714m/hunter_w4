"""Tests unitarios de URLSeenFilter."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.db import SQLiteOfferRepository
from src.core.normalize import canonicalize_url, stable_offer_id
from src.core.url_seen_filter import URLSeenFilter


def _make_repo(*, is_dup: bool = False, has_any: set[str] | None = None) -> MagicMock:
    repo = MagicMock(spec=SQLiteOfferRepository)
    repo.is_duplicate.return_value = is_dup
    repo.has_any.return_value = has_any or set()
    return repo


# ---------------------------------------------------------------------------
# is_seen
# ---------------------------------------------------------------------------

def test_is_seen_returns_false_for_unknown_url() -> None:
    f = URLSeenFilter(_make_repo(is_dup=False))
    assert f.is_seen('linkedin', 'https://linkedin.com/jobs/view/123') is False


def test_is_seen_returns_true_for_known_url() -> None:
    f = URLSeenFilter(_make_repo(is_dup=True))
    assert f.is_seen('linkedin', 'https://linkedin.com/jobs/view/123') is True


def test_is_seen_with_empty_url_returns_false() -> None:
    repo = _make_repo()
    f = URLSeenFilter(repo)
    assert f.is_seen('elempleo', '') is False
    repo.is_duplicate.assert_not_called()


def test_is_seen_with_invalid_url_returns_false() -> None:
    # canonicalize_url prepends https:// to scheme-less strings, so only
    # an empty string raises ValueError and short-circuits the DB query.
    repo = _make_repo(is_dup=False)
    f = URLSeenFilter(repo)
    assert f.is_seen('elempleo', 'no-es-una-url-valida') is False


def test_is_seen_calls_is_duplicate_with_correct_id() -> None:
    url = 'https://elempleo.com/co/ofertas-trabajo/dev-python/123'
    canonical = canonicalize_url(url)
    expected_id = stable_offer_id('elempleo', canonical)

    repo = _make_repo(is_dup=False)
    URLSeenFilter(repo).is_seen('elempleo', url)

    repo.is_duplicate.assert_called_once_with(expected_id)


# ---------------------------------------------------------------------------
# bulk_seen
# ---------------------------------------------------------------------------

def test_bulk_seen_makes_single_query() -> None:
    repo = _make_repo()
    f = URLSeenFilter(repo)
    f.bulk_seen('elempleo', [
        'https://elempleo.com/co/ofertas-trabajo/a/1',
        'https://elempleo.com/co/ofertas-trabajo/b/2',
    ])
    repo.has_any.assert_called_once()


def test_bulk_seen_returns_matching_urls() -> None:
    url = 'https://elempleo.com/co/ofertas-trabajo/dev-python/123'
    other = 'https://elempleo.com/co/ofertas-trabajo/other/456'
    offer_id = stable_offer_id('elempleo', canonicalize_url(url))

    repo = _make_repo(has_any={offer_id})
    f = URLSeenFilter(repo)
    seen = f.bulk_seen('elempleo', [url, other])

    assert url in seen
    assert other not in seen


def test_bulk_seen_returns_empty_when_none_known() -> None:
    repo = _make_repo(has_any=set())
    f = URLSeenFilter(repo)
    seen = f.bulk_seen('linkedin', [
        'https://linkedin.com/jobs/view/111',
        'https://linkedin.com/jobs/view/222',
    ])
    assert seen == set()


def test_bulk_seen_empty_list_returns_empty_set() -> None:
    repo = _make_repo()
    f = URLSeenFilter(repo)
    seen = f.bulk_seen('elempleo', [])
    assert seen == set()
    repo.has_any.assert_not_called()


def test_bulk_seen_skips_invalid_urls() -> None:
    repo = _make_repo(has_any=set())
    f = URLSeenFilter(repo)
    seen = f.bulk_seen('elempleo', ['', 'no-url', 'https://valid.com/offer/1'])
    assert '' not in seen
    assert 'no-url' not in seen


def test_bulk_seen_empty_string_only_no_query() -> None:
    # Only an empty string raises ValueError in canonicalize_url and is skipped.
    # Text strings (e.g. 'no-es-url') receive https:// and produce a valid ID.
    repo = _make_repo(has_any=set())
    f = URLSeenFilter(repo)
    seen = f.bulk_seen('elempleo', [''])
    assert seen == set()
    repo.has_any.assert_not_called()
