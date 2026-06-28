"""Pruebas unitarias de PipelineGraph.

Cada test verifica que la oferta termina en el estado correcto
según la capa de la cascada que la descarta. Todos los servicios
externos (DB, embeddings, juez, Telegram) se reemplazan con stubs.
"""
from __future__ import annotations

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from datetime import date as _date

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.core.normalize import OfferNormalizer
from src.core.db import SQLiteOfferRepository
from src.filters.date_filter import DateFilter
from src.filters.language import LanguageFilter
from src.filters.skill_filter import SkillFilter
from src.graph.pipeline import PipelineGraph, PipelineResult


# ---------------------------------------------------------------------------
# Factories de stubs
# ---------------------------------------------------------------------------

def _make_repo(*, is_dup: bool = False) -> MagicMock:
    repo = MagicMock(spec=SQLiteOfferRepository)
    repo.is_duplicate.return_value = is_dup
    return repo


def _make_store(*, distance: float = 0.1) -> MagicMock:
    """distance=0.1 → similitud≈0.95 (pasa umbral 0.5)."""
    store = MagicMock()
    store.search.return_value = [{'id': 'perfil-frag-1', 'text': 'frag', 'score': distance}]
    store.upsert.return_value = None
    return store


def _make_judge(*, apto: bool = True, score: float = 0.9) -> MagicMock:
    judge = MagicMock()
    judge.judge.return_value = MatchVerdict(
        score=score,
        apto=apto,
        razon='test',
        puntos_favor=['a'],
        puntos_contra=['b'],
    )
    return judge


def _make_notifier(*, raises: bool = False) -> MagicMock:
    notifier = MagicMock()
    if raises:
        from src.notify.telegram_notifier import TelegramNotifierError
        notifier.notify.side_effect = TelegramNotifierError('fallo')
    return notifier


def _make_exporter(*, raises: bool = False) -> MagicMock:
    exporter = MagicMock()
    if raises:
        from src.notify.markdown_exporter import MarkdownExporterError
        exporter.export.side_effect = MarkdownExporterError('fallo')
    return exporter


def _make_offer_model() -> Offer:
    """Offer Pydantic mínima para tests de nodos LangGraph."""
    return Offer(
        id='a' * 64,
        fuente='linkedin',
        url='https://linkedin.com/jobs/view/999',
        titulo='Test Offer',
        descripcion_md='Python FastAPI Docker backend role.',
        posted_date=_date.today(),
    )


def _raw_offer(
    *,
    titulo: str = 'Python Developer',
    url: str = 'https://linkedin.com/jobs/view/123',
    descripcion_md: str = 'Python FastAPI Docker backend developer',
    posted_date: str | None = None,
    fuente: str = 'linkedin',
) -> dict:
    return {
        'titulo': titulo,
        'url': url,
        'descripcion_md': descripcion_md,
        'posted_date': posted_date,
        'fuente': fuente,
    }


def _make_pipeline(
    *,
    repo: MagicMock | None = None,
    store: MagicMock | None = None,
    judge: MagicMock | None = None,
    notifier: MagicMock | None = None,
    exporter: MagicMock | None = None,
    max_days: int = 30,
    idiomas: list[str] | None = None,
    skills: list[str] | None = None,
    umbral_skills: float = 0.5,
    umbral_similitud: float = 0.5,
) -> PipelineGraph:
    return PipelineGraph(
        repo=repo or _make_repo(),
        normalizer=OfferNormalizer(),
        date_filter=DateFilter(max_days=max_days),
        lang_filter=LanguageFilter(idiomas_permitidos=idiomas or ['ES', 'EN']),
        skill_filter=SkillFilter(
            required_skills=skills or ['Python', 'FastAPI', 'Docker'],
            umbral_match=umbral_skills,
        ),
        embedder=MagicMock(),
        store=store or _make_store(),
        judge=judge or _make_judge(),
        notifier=notifier or _make_notifier(),
        exporter=exporter or _make_exporter(),
        umbral_similitud=umbral_similitud,
        namespace_ofertas='ofertas',
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_duplicate_offer_is_skipped_silently(self) -> None:
        pipeline = _make_pipeline(repo=_make_repo(is_dup=True))
        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.skipped is True
        assert result.estado_final == 'duplicate'
        pipeline.repo.save_state.assert_not_called()


class TestDateFilter:
    def test_old_offer_is_discarded(self) -> None:
        old_date = (date.today() - timedelta(days=60)).isoformat()
        pipeline = _make_pipeline(max_days=7)

        result = pipeline.process(_raw_offer(posted_date=old_date), 'elempleo')

        assert result.estado_final == 'old'
        pipeline.repo.save_state.assert_called_once()
        args = pipeline.repo.save_state.call_args[0]
        assert args[1] == 'old'

    def test_recent_offer_passes_date_filter(self) -> None:
        recent_date = date.today().isoformat()
        pipeline = _make_pipeline(max_days=7)

        result = pipeline.process(_raw_offer(posted_date=recent_date), 'elempleo')

        # No debe terminar en 'old'
        assert result.estado_final != 'old'


class TestLanguageFilter:
    def test_non_allowed_language_is_discarded(self) -> None:
        # Texto en alemán — claramente no ES ni EN
        raw = _raw_offer(
            descripcion_md=(
                'Wir suchen einen erfahrenen Python-Entwickler für unser Team in Berlin. '
                'Sie sollten Kenntnisse in FastAPI und Docker mitbringen und '
                'mindestens drei Jahre Berufserfahrung in der Softwareentwicklung haben.'
            )
        )
        pipeline = _make_pipeline(idiomas=['ES', 'EN'])

        result = pipeline.process(raw, 'linkedin')

        assert result.estado_final == 'other_lang'
        args = pipeline.repo.save_state.call_args[0]
        assert args[1] == 'other_lang'


class TestSkillFilter:
    def test_offer_without_enough_skills_is_discarded(self) -> None:
        raw = _raw_offer(descripcion_md='Buscamos desarrollador con experiencia en Java y Spring.')
        pipeline = _make_pipeline(
            skills=['Python', 'FastAPI', 'Docker'],
            umbral_skills=0.5,
        )

        result = pipeline.process(raw, 'linkedin')

        assert result.estado_final == 'low_skills'
        call_kwargs = pipeline.repo.save_state.call_args
        estado = call_kwargs[0][1] if call_kwargs[0] else call_kwargs[1].get('estado')
        assert estado == 'low_skills' or call_kwargs[0][1] == 'low_skills'

    def test_offer_with_enough_skills_passes(self) -> None:
        raw = _raw_offer(descripcion_md='Python developer with FastAPI and Docker. Great opportunity.')
        pipeline = _make_pipeline(
            skills=['Python', 'FastAPI', 'Docker'],
            umbral_skills=0.5,
        )

        result = pipeline.process(raw, 'linkedin')

        assert result.estado_final != 'low_skills'


class TestSimilarityFilter:
    def test_low_similarity_offer_is_discarded(self) -> None:
        # distance=1.8 → similitud = 1 - 1.8/2 = 0.1 < umbral 0.5
        pipeline = _make_pipeline(
            store=_make_store(distance=1.8),
            umbral_similitud=0.5,
        )

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'low_sim'

    def test_high_similarity_offer_passes(self) -> None:
        # distance=0.1 → similitud ≈ 0.95 > umbral 0.5
        pipeline = _make_pipeline(
            store=_make_store(distance=0.1),
            umbral_similitud=0.5,
        )

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final != 'low_sim'

    def test_no_profile_indexed_lets_offer_pass(self) -> None:
        store = MagicMock()
        store.search.return_value = []  # sin perfil indexado
        store.upsert.return_value = None
        pipeline = _make_pipeline(store=store, umbral_similitud=0.5)

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final != 'low_sim'


class TestJudge:
    def test_judge_rejection_marks_low_sim(self) -> None:
        pipeline = _make_pipeline(judge=_make_judge(apto=False, score=0.2))

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'low_sim'

    def test_judge_approval_reaches_notification(self) -> None:
        pipeline = _make_pipeline(judge=_make_judge(apto=True, score=0.9))

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final in ('notified', 'notify_failed')

    def test_judge_error_does_not_mark_matched(self) -> None:
        """Bug K: OllamaJudgeError no debe guardar 'matched'; pone oferta en pausa con 'low_sim'."""
        from src.judge.ollama_judge import OllamaJudgeError
        judge = MagicMock()
        judge.judge.side_effect = OllamaJudgeError('timeout')
        pipeline = _make_pipeline(judge=judge)

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'low_sim'
        assert result.skipped is False
        args = pipeline.repo.save_state.call_args[0]
        assert args[1] == 'low_sim'
        assert args[1] != 'matched'

    def test_judge_error_does_not_notify(self) -> None:
        """Bug K: cuando el juez falla no debe llamar a notifier ni exporter."""
        from src.judge.ollama_judge import OllamaJudgeError
        judge = MagicMock()
        judge.judge.side_effect = OllamaJudgeError('timeout')
        notifier = _make_notifier()
        exporter = _make_exporter()
        pipeline = _make_pipeline(judge=judge, notifier=notifier, exporter=exporter)

        pipeline.process(_raw_offer(), 'linkedin')

        notifier.notify.assert_not_called()
        exporter.export.assert_not_called()


class TestNotification:
    def test_both_outputs_ok_marks_notified(self) -> None:
        pipeline = _make_pipeline(
            notifier=_make_notifier(raises=False),
            exporter=_make_exporter(raises=False),
        )

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'notified'

    def test_telegram_fails_but_md_ok_marks_notified(self) -> None:
        pipeline = _make_pipeline(
            notifier=_make_notifier(raises=True),
            exporter=_make_exporter(raises=False),
        )

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'notified'

    def test_both_fail_marks_notify_failed(self) -> None:
        pipeline = _make_pipeline(
            notifier=_make_notifier(raises=True),
            exporter=_make_exporter(raises=True),
        )

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'notify_failed'

    def test_no_notifier_configured_still_exports_md(self) -> None:
        exporter = _make_exporter(raises=False)
        pipeline = _make_pipeline(notifier=None, exporter=exporter)

        result = pipeline.process(_raw_offer(), 'linkedin')

        assert result.estado_final == 'notified'
        exporter.export.assert_called_once()


class TestNormalizationError:
    def test_raw_without_url_is_skipped(self) -> None:
        raw: dict = {'titulo': 'Dev', 'descripcion_md': 'Python dev'}  # sin url
        pipeline = _make_pipeline()

        result = pipeline.process(raw, 'linkedin')

        assert result.skipped is True


# ---------------------------------------------------------------------------
# Tests de nodos LangGraph individuales (Correcciones F, H, J)
# ---------------------------------------------------------------------------

class TestPersistirGuard:
    """Corrección F — node_persistir rechaza estado_final vacío."""

    def test_persistir_raises_if_estado_vacio(self) -> None:
        """estado_final='' con offer válida → RuntimeError, no guardado silencioso."""
        pipeline = _make_pipeline()
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': None,
            'estado_final': '',
            'descartada': False,
        }
        with pytest.raises(RuntimeError, match='estado_final vacío'):
            pipeline.node_persistir(fake_state)

    def test_persistir_does_not_call_save_state_on_duplicate(self) -> None:
        """Corrección B: estado='duplicate' → node_persistir retorna {} sin llamar save_state."""
        pipeline = _make_pipeline()
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': None,
            'estado_final': 'duplicate',
            'descartada': True,
        }
        result = pipeline.node_persistir(fake_state)
        assert result == {}
        pipeline.repo.save_state.assert_not_called()

    def test_persistir_does_not_call_save_state_when_offer_is_none(self) -> None:
        """Corrección A: normalización fallida → offer=None → node_persistir retorna {} sin DB."""
        pipeline = _make_pipeline()
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': None,
            'similitud': None,
            'estado_final': 'error_normalizacion',
            'descartada': True,
        }
        result = pipeline.node_persistir(fake_state)
        assert result == {}
        pipeline.repo.save_state.assert_not_called()


class TestNodeSimilitud:
    """Corrección H — node_similitud nunca compara None < float."""

    def test_none_similarity_does_not_raise_type_error(self) -> None:
        """Perfil no indexado → similitud=None → oferta pasa sin TypeError."""
        store = MagicMock()
        store.search.return_value = []
        pipeline = _make_pipeline(store=store, umbral_similitud=0.5)
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': None,
            'estado_final': '',
            'descartada': False,
        }
        result = pipeline.node_similitud(fake_state)
        assert result.get('descartada') is not True

    def test_none_similarity_stored_as_none_in_result(self) -> None:
        """similitud=None se propaga en el estado sin lanzar error."""
        store = MagicMock()
        store.search.return_value = []
        pipeline = _make_pipeline(store=store)
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': None,
            'estado_final': '',
            'descartada': False,
        }
        result = pipeline.node_similitud(fake_state)
        assert result.get('similitud') is None

    def test_low_similarity_sets_descartada(self) -> None:
        """similitud baja → descartada=True, estado_final='low_sim'."""
        store = MagicMock()
        store.search.return_value = [{'id': 'p1', 'text': 'frag', 'score': 1.8}]
        pipeline = _make_pipeline(store=store, umbral_similitud=0.5)
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': None,
            'estado_final': '',
            'descartada': False,
        }
        result = pipeline.node_similitud(fake_state)
        assert result.get('descartada') is True
        assert result.get('estado_final') == 'low_sim'


class TestNodeIndexar:
    """Corrección J — node_indexar atrapa excepciones y siempre retorna {}."""

    def test_indexar_swallows_lancedb_exception(self) -> None:
        """Excepción en store.upsert no interrumpe el grafo."""
        store = MagicMock()
        store.upsert.side_effect = Exception('LanceDB caído')
        pipeline = _make_pipeline(store=store)
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': 0.9,
            'estado_final': '',
            'descartada': False,
        }
        result = pipeline.node_indexar(fake_state)
        assert result == {}

    def test_indexar_ok_returns_empty_dict(self) -> None:
        """Indexado exitoso retorna {} (efecto secundario puro)."""
        store = MagicMock()
        store.upsert.return_value = None
        pipeline = _make_pipeline(store=store)
        fake_state = {
            'raw': {}, 'source': 'linkedin',
            'offer': _make_offer_model(),
            'similitud': 0.9,
            'estado_final': '',
            'descartada': False,
        }
        result = pipeline.node_indexar(fake_state)
        assert result == {}
        store.upsert.assert_called_once()
