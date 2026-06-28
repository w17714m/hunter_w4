from __future__ import annotations

import logging

from src.core.db import SQLiteOfferRepository
from src.core.normalize import canonicalize_url, stable_offer_id

logger = logging.getLogger(__name__)


class URLSeenFilter:
    """Consulta SQLite para saber si una URL ya fue procesada antes del scraping.

    Uso principal: collectors la llaman con bulk_seen() sobre la lista de URLs
    del listado de resultados, antes de navegar a cada página de detalle.
    node_dedup en el pipeline sigue siendo la defensa final ante condiciones de carrera.
    """

    def __init__(self, repo: SQLiteOfferRepository) -> None:
        self._repo = repo

    def is_seen(self, source: str, url: str) -> bool:
        """True si la URL ya fue procesada (existe en DB). Ignora URLs inválidas."""
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            return False
        return self._repo.is_duplicate(stable_offer_id(source, canonical))

    def bulk_seen(self, source: str, urls: list[str]) -> set[str]:
        """Retorna el subconjunto de urls que ya están en DB. Una sola query SQL."""
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
