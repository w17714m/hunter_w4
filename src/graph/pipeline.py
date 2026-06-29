from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph

from src.core.db import SQLiteOfferRepository
from src.core.models import Offer
from src.core.normalize import OfferNormalizer, SourceName
from src.embeddings.ollama_embedder import OllamaEmbedder, OllamaEmbedderError
from src.embeddings.vector_store import LanceDbStore
from src.filters.date_filter import DateFilter
from src.filters.language import LanguageFilter
from src.filters.skill_filter import SkillFilter
from src.graph.state import PipelineState
from src.judge.ollama_judge import OllamaJudge, OllamaJudgeError
from src.notify.markdown_exporter import MarkdownExporter, MarkdownExporterError
from src.notify.telegram_notifier import TelegramNotifier, TelegramNotifierError

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    offer_id: str
    estado_final: str
    skipped: bool = False  # True solo para "duplicate" y "error_normalizacion"


def _initial_state(raw: dict[str, Any], source: str) -> PipelineState:
    """Estado inicial completo requerido por graph.invoke()."""
    return {
        'raw': raw,
        'source': source,
        'offer': None,
        'similitud': None,
        'estado_final': '',
        'descartada': False,
    }


def _route(dest: str):
    """Return a router that redirects to `dest` if the offer has not been discarded."""
    def router(state: PipelineState) -> str:
        return 'persistir' if state['descartada'] else dest
    return router


@dataclass
class PipelineGraph:
    """Orchestrates the offer processing pipeline using LangGraph.

    The graph follows the cascade: normalize → dedup → date → language → skills
    → similarity → judge → index → notify → persist.

    All nodes that can discard an offer have a conditional edge to 'persist',
    which finalizes the graph by updating the offer state in SQLite.
    """

    repo: SQLiteOfferRepository
    normalizer: OfferNormalizer
    date_filter: DateFilter
    lang_filter: LanguageFilter
    skill_filter: SkillFilter
    embedder: OllamaEmbedder
    store: LanceDbStore
    judge: OllamaJudge
    notifier: TelegramNotifier | None
    exporter: MarkdownExporter
    umbral_similitud: float
    namespace_ofertas: str = 'ofertas'

    def __post_init__(self) -> None:
        self._graph = _build_graph(self)

    def process(self, raw: dict[str, Any], source: SourceName) -> PipelineResult:
        """Public wrapper over graph.invoke() — preserves the original interface."""
        state = self._graph.invoke(_initial_state(raw, source))
        estado = state['estado_final']
        offer_id = state['offer'].id if state['offer'] is not None else 'unknown'
        # "duplicate" and "error_normalizacion" are silent discards (skipped=True).
        # Other discards (old, other_lang, low_skills, low_sim) have skipped=False.
        skipped = estado in ('duplicate', 'error_normalizacion')
        return PipelineResult(offer_id=offer_id, estado_final=estado, skipped=skipped)

    # ------------------------------------------------------------------
    # Nodos del grafo
    # ------------------------------------------------------------------

    def node_normalizar(self, state: PipelineState) -> dict:
        try:
            offer = self.normalizer.normalize(state['source'], state['raw'])
            return {'offer': offer}
        except ValueError as exc:
            logger.warning('Normalization failed for offer from %s: %s', state['source'], exc)
            return {'descartada': True, 'estado_final': 'error_normalizacion'}

    def node_dedup(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        if self.repo.is_duplicate(offer.id):
            logger.debug('Duplicate offer ignored: %s', offer.id[:12])
            return {'descartada': True, 'estado_final': 'duplicate'}
        self.repo.upsert(offer)
        return {}

    def node_fecha(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        result = self.date_filter.apply(offer)
        if not result.pasa:
            logger.info('[%s] Descartada por fecha: %s', offer.id[:12], offer.titulo)
            return {'descartada': True, 'estado_final': 'old'}
        return {}

    def node_idioma(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        result = self.lang_filter.apply(offer)
        if not result.pasa:
            logger.info(
                '[%s] Descartada por idioma (%s): %s',
                offer.id[:12], result.idioma_detectado, offer.titulo,
            )
            return {'descartada': True, 'estado_final': 'other_lang'}
        return {}

    def node_skills(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        offer = self.skill_filter.attach(offer)
        skill_match = offer.skill_match
        assert skill_match is not None
        if not skill_match.pasa:
            logger.info(
                '[%s] Descartada por skills (%.0f%%): %s',
                offer.id[:12], skill_match.fraccion * 100, offer.titulo,
            )
            return {'offer': offer, 'descartada': True, 'estado_final': 'low_skills'}
        return {'offer': offer}

    def node_similitud(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        similitud = self._compute_similarity(offer)
        # Fix H: never compare None with float
        if similitud is not None and similitud < self.umbral_similitud:
            logger.info(
                '[%s] Descartada por similitud (%.2f < %.2f): %s',
                offer.id[:12], similitud, self.umbral_similitud, offer.titulo,
            )
            return {'similitud': similitud, 'descartada': True, 'estado_final': 'low_sim'}
        return {'similitud': similitud}

    def node_juez(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        similitud = state['similitud']
        skill_match = offer.skill_match
        try:
            veredicto = self.judge.judge(offer)
        except OllamaJudgeError as exc:
            # Bug K: judge down → pause the offer, do NOT mark it as approved
            logger.error('[%s] Judge failed (offer on hold): %s', offer.id[:12], exc)
            return {'descartada': True, 'estado_final': 'low_sim'}

        if not veredicto.apto:
            logger.info('[%s] Judge rejected (score=%.2f): %s', offer.id[:12], veredicto.score, offer.titulo)
            return {'descartada': True, 'estado_final': 'low_sim'}

        logger.info('[%s] ✅ Match aprobado (score=%.2f): %s', offer.id[:12], veredicto.score, offer.titulo)
        updated_offer = offer.model_copy(update={'veredicto': veredicto, 'similitud': similitud})
        return {'offer': updated_offer, 'estado_final': 'matched'}

    def node_indexar(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        # Fix J: LanceDB exception must not terminate the graph
        try:
            self.store.upsert(self.namespace_ofertas, offer.id, offer.descripcion_md)
        except Exception as exc:
            logger.warning('[%s] No se pudo indexar la oferta: %s', offer.id[:12], exc)
        return {}

    def node_notificar(self, state: PipelineState) -> dict:
        offer: Offer = state['offer']
        telegram_ok = False
        md_ok = False

        if self.notifier is not None:
            try:
                self.notifier.notify(offer)
                telegram_ok = True
                logger.info('[%s] Telegram enviado', offer.id[:12])
            except TelegramNotifierError as exc:
                logger.error('[%s] Telegram failed: %s', offer.id[:12], exc)

        try:
            self.exporter.export(offer)
            md_ok = True
            logger.info('[%s] Archivo .md exportado', offer.id[:12])
        except MarkdownExporterError as exc:
            logger.error('[%s] .md export failed: %s', offer.id[:12], exc)

        estado = 'notified' if (telegram_ok or md_ok) else 'notify_failed'
        return {'estado_final': estado}

    def node_persistir(self, state: PipelineState) -> dict:
        offer = state['offer']
        estado = state['estado_final']

        if offer is None:
            # normalization failed before upsert; no row exists in DB
            return {}

        if estado == 'duplicate':
            # la fila ya existe con su estado original; no sobrescribir
            return {}

        # Fix F: empty estado_final indicates a routing bug — fail loudly
        if not estado:
            raise RuntimeError(
                f'node_persistir reached with empty estado_final for offer={offer.id}'
            )

        # Fix B: "error_normalizacion" never reaches here (conditional edge after normalize),
        # but if it ever did due to a bug, save_state would fail because no row exists in DB.
        # The earlier guard (offer is None) already covers this; this comment documents the invariant.

        self.repo.save_state(
            offer.id,
            estado,
            skill_match=offer.skill_match,
            similitud=state['similitud'],
            veredicto=offer.veredicto,
        )
        return {}

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _compute_similarity(self, offer: Offer) -> float | None:
        """Compute cosine similarity between the offer and the indexed profile.

        Returns None if the profile is not indexed (offer passes through).
        LanceDB uses cosine distance: 0=identical, 2=opposite → sim = 1 - dist/2.
        """
        try:
            results = self.store.search(
                namespace='perfil',
                query_text=offer.descripcion_md,
                top_k=1,
            )
        except Exception as exc:
            logger.warning('[%s] Error al buscar similitud vectorial: %s', offer.id[:12], exc)
            return None

        if not results:
            logger.debug('[%s] Profile not indexed; similarity skipped', offer.id[:12])
            return None

        distance = float(results[0]['score'])
        return max(0.0, 1.0 - distance / 2.0)


def _build_graph(deps: PipelineGraph):
    """Build and compile the LangGraph with all conditional edges."""
    g = StateGraph(PipelineState)

    g.add_node('normalizar', deps.node_normalizar)
    g.add_node('dedup',      deps.node_dedup)
    g.add_node('fecha',      deps.node_fecha)
    g.add_node('idioma',     deps.node_idioma)
    g.add_node('skills',     deps.node_skills)
    g.add_node('similitud',  deps.node_similitud)
    g.add_node('juez',       deps.node_juez)
    g.add_node('indexar',    deps.node_indexar)
    g.add_node('notificar',  deps.node_notificar)
    g.add_node('persistir',  deps.node_persistir)

    g.set_entry_point('normalizar')

    # Fix A: normalize also has a conditional edge
    g.add_conditional_edges('normalizar', _route('dedup'),     {'persistir': 'persistir', 'dedup':     'dedup'})
    g.add_conditional_edges('dedup',      _route('fecha'),     {'persistir': 'persistir', 'fecha':     'fecha'})
    g.add_conditional_edges('fecha',      _route('idioma'),    {'persistir': 'persistir', 'idioma':    'idioma'})
    g.add_conditional_edges('idioma',     _route('skills'),    {'persistir': 'persistir', 'skills':    'skills'})
    g.add_conditional_edges('skills',     _route('similitud'), {'persistir': 'persistir', 'similitud': 'similitud'})
    g.add_conditional_edges('similitud',  _route('juez'),      {'persistir': 'persistir', 'juez':      'juez'})
    g.add_conditional_edges('juez',       _route('indexar'),   {'persistir': 'persistir', 'indexar':   'indexar'})

    # Fix 4: index runs after the judge (only approved offers are indexed)
    g.add_edge('indexar',   'notificar')
    g.add_edge('notificar', 'persistir')
    g.add_edge('persistir', END)

    return g.compile()
