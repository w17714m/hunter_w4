from __future__ import annotations

import logging

from src.core.db import SQLiteOfferRepository
from src.core.normalize import canonicalize_url, stable_offer_id

logger = logging.getLogger(__name__)


class URLSeenFilter:
    """Query SQLite to check whether a URL has already been processed before scraping.

    Primary use: collectors call bulk_seen() on the result listing URLs,
    before navigating to each detail page.
    node_dedup in the pipeline remains the final defense against race conditions.
    """

    def __init__(self, repo: SQLiteOfferRepository) -> None:
        self._repo = repo

    def is_seen(self, source: str, url: str) -> bool:
        """True if the URL has already been processed (exists in DB). Ignores invalid URLs."""
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            return False
        return self._repo.is_duplicate(stable_offer_id(source, canonical))

    def bulk_seen(self, source: str, urls: list[str]) -> set[str]:
        """Return the subset of urls already in DB. Single SQL query."""
        id_to_url: dict[str, str] = {}
        for url in urls:
            try:
                canonical = canonicalize_url(url)
            except ValueError:
                continue
            id_to_url[stable_offer_id(source, canonical)] = url

        if not id_to_url:
            return set()

        seen_ids = self._repo.has_any(list(id_to_url))
        return {id_to_url[oid] for oid in seen_ids}
