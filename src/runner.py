from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from src.collectors.computrabajo import ComputrabajoCollector
from src.collectors.elempleo import ElempleoCollector
from src.collectors.linkedin import LinkedInCollector
from src.config.loaders import get_config, clear_config_cache
from src.stealth.warp_rotator import WarpRotator
from src.core.db import SQLiteOfferRepository
from src.core.url_seen_filter import URLSeenFilter
from src.core.visit_budget import VisitBudget
from src.core.normalize import OfferNormalizer
from src.embeddings.ollama_embedder import OllamaEmbedder
from src.embeddings.vector_store import LanceDbStore
from src.filters.date_filter import DateFilter
from src.filters.language import LanguageFilter
from src.filters.skill_extractor import LLMSkillExtractor
from src.filters.skill_filter import SkillFilter
from src.graph.pipeline import PipelineGraph
from src.judge.ollama_judge import OllamaJudge
from src.notify.markdown_exporter import MarkdownExporter
from src.notify.telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def _build_pipeline(cfg: Any, repo: SQLiteOfferRepository | None = None) -> PipelineGraph:
    repo = repo or SQLiteOfferRepository()
    normalizer = OfferNormalizer()

    date_filter = DateFilter(max_days=cfg.filtros.max_days)
    lang_filter = LanguageFilter(idiomas_permitidos=cfg.filtros.idiomas_permitidos)
    skill_extractor = LLMSkillExtractor(
        base_url=cfg.modelos.ollama_base_url,
        model=cfg.modelos.extractor_skills,
    )
    skill_filter = SkillFilter(
        required_skills=cfg.skills.lista,
        umbral_match=cfg.skills.umbral_match,
        extractor=skill_extractor,
    )

    embedder = OllamaEmbedder(
        base_url=cfg.modelos.ollama_base_url,
        model=cfg.modelos.embeddings,
    )
    store = LanceDbStore(path=cfg.vectores.path, embedder=embedder)
    judge = OllamaJudge(
        store=store,
        base_url=cfg.modelos.ollama_base_url,
        model=cfg.modelos.juez,
        truncar_chars=cfg.filtros.truncar_descripcion_chars,
    )

    notifier: TelegramNotifier | None = None
    if cfg.notificacion.telegram_habilitado:
        notifier = TelegramNotifier(
            token=cfg.notificacion.telegram_token,
            chat_id=cfg.notificacion.telegram_chat_id,
        )

    exporter = MarkdownExporter(output_dir=cfg.salidas.markdown_dir)

    return PipelineGraph(
        repo=repo,
        normalizer=normalizer,
        date_filter=date_filter,
        lang_filter=lang_filter,
        skill_filter=skill_filter,
        embedder=embedder,
        store=store,
        judge=judge,
        notifier=notifier,
        exporter=exporter,
        umbral_similitud=cfg.filtros.umbral_similitud,
        namespace_ofertas=cfg.vectores.namespace_ofertas,
    )


async def _collect_all(
    cfg: Any,
    url_filter: URLSeenFilter | None = None,
    max_per_source: int | None = None,
    linkedin_budget: VisitBudget | None = None,
    repo: SQLiteOfferRepository | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """Launch all three collectors and return a list of (raw_offer, source).

    url_filter skips already-processed URLs before navigating to the detail page.
    max_per_source limits how many offers are extracted per source (useful for --trial).
    """
    raw_pairs: list[tuple[dict[str, Any], str]] = []

    busquedas_e = [b.model_dump() for b in cfg.busquedas.elempleo]
    busquedas_li = [b.model_dump() for b in cfg.busquedas.linkedin]
    busquedas_ct = [b.model_dump() for b in cfg.busquedas.computrabajo]

    headless = cfg.browser.headless

    # Single WarpRotator instance shared by all collectors; its internal lock
    # prevents concurrent rotations even when collectors run in parallel.
    warp = WarpRotator(
        warp_cli_path=cfg.stealth.warp_cli_path,
        enabled=cfg.stealth.warp_enabled,
    ) if cfg.stealth.warp_enabled else None
    max_rotations = cfg.stealth.max_ip_rotations

    fuentes = cfg.fuentes

    if busquedas_e:
        logger.info('Collecting elempleo (%d searches)...', len(busquedas_e))
        try:
            collector_e = ElempleoCollector(
                max_offers_per_search=max_per_source,
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                base_url=fuentes.elempleo_base_url,
            ) if max_per_source else ElempleoCollector(
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                base_url=fuentes.elempleo_base_url,
            )
            raw_e = await collector_e.collect(busquedas_e[:1] if max_per_source else busquedas_e)
            raw_pairs.extend((r, 'elempleo') for r in raw_e)
            logger.info('elempleo: %d raw results', len(raw_e))
        except Exception as exc:
            logger.error('Elempleo collector failed: %s', exc)

    if busquedas_li:
        logger.info('Collecting LinkedIn (%d searches)...', len(busquedas_li))
        try:
            collector_li = LinkedInCollector(
                max_offers_per_search=max_per_source,
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                visit_budget=linkedin_budget,
                base_url=fuentes.linkedin_base_url,
                ollama_base_url=cfg.modelos.ollama_base_url,
                extractor_html_model=cfg.modelos.extractor_html,
                repo=repo,
            ) if max_per_source else LinkedInCollector(
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                visit_budget=linkedin_budget,
                base_url=fuentes.linkedin_base_url,
                ollama_base_url=cfg.modelos.ollama_base_url,
                extractor_html_model=cfg.modelos.extractor_html,
                repo=repo,
            )
            raw_li = await collector_li.collect(busquedas_li[:1] if max_per_source else busquedas_li)
            raw_pairs.extend((r, 'linkedin') for r in raw_li)
            logger.info('LinkedIn: %d raw results', len(raw_li))
        except Exception as exc:
            logger.error('LinkedIn collector failed: %s', exc)

    if busquedas_ct:
        logger.info('Collecting Computrabajo (%d searches)...', len(busquedas_ct))
        try:
            collector_ct = ComputrabajoCollector(
                max_offers_per_search=max_per_source,
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                base_url=fuentes.computrabajo_base_url,
            ) if max_per_source else ComputrabajoCollector(
                headless=headless,
                warp_rotator=warp,
                max_ip_rotations=max_rotations,
                url_filter=url_filter,
                base_url=fuentes.computrabajo_base_url,
            )
            raw_ct = await collector_ct.collect(busquedas_ct[:1] if max_per_source else busquedas_ct)
            raw_pairs.extend((r, 'computrabajo') for r in raw_ct)
            logger.info('Computrabajo: %d raw results', len(raw_ct))
        except Exception as exc:
            logger.error('Computrabajo collector failed: %s', exc)

    return raw_pairs


async def run_once() -> None:
    cfg = get_config()
    repo = SQLiteOfferRepository()
    url_filter = URLSeenFilter(repo)
    pipeline = _build_pipeline(cfg, repo=repo)
    linkedin_budget = VisitBudget(limit=150)

    raw_pairs = await _collect_all(cfg, url_filter=url_filter, linkedin_budget=linkedin_budget, repo=repo)
    logger.info('Total raw offers received: %d', len(raw_pairs))

    counts: dict[str, int] = {}
    for raw, source in raw_pairs:
        # Skip results with a non-recoverable extraction_status
        status = raw.get('extraction_status', 'ok')
        if status in ('login_required', 'blocked', 'captcha', 'empty_description'):
            logger.warning('[%s] Offer skipped due to status: %s | %s', source, status, raw.get('url', ''))
            continue

        result = pipeline.process(raw, source)  # type: ignore[arg-type]
        counts[result.estado_final] = counts.get(result.estado_final, 0) + 1

    logger.info('Cycle complete. Summary: %s', counts)


async def run_trial() -> None:
    """Trial cycle: 1 offer per source, full cascade with detailed logs, no scheduler."""
    cfg = get_config()
    repo = SQLiteOfferRepository()
    # trial skips url_filter — allows reprocessing to inspect the full pipeline flow
    pipeline = _build_pipeline(cfg, repo=repo)

    logger.info('=== TRIAL MODE — 1 offer per source, full flow ===')
    raw_pairs = await _collect_all(cfg, max_per_source=1, repo=repo)
    logger.info('Total raw offers for trial: %d', len(raw_pairs))

    for i, (raw, source) in enumerate(raw_pairs, start=1):
        url = raw.get('url', 'sin-url')
        status = raw.get('extraction_status', 'ok')
        logger.info('--- [%d/%d] %s | %s | extraction status: %s', i, len(raw_pairs), source, url, status)

        if status in ('login_required', 'blocked', 'captcha', 'empty_description'):
            logger.warning('  → Skipped (non-recoverable extraction)')
            continue

        result = pipeline.process(raw, source)  # type: ignore[arg-type]
        logger.info('  → Estado final: %s | skipped: %s', result.estado_final, result.skipped)

    logger.info('=== TRIAL COMPLETE ===')


def _run_scheduler(interval_minutes: int) -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        logger.error('APScheduler is not installed. Install with: uv add apscheduler')
        sys.exit(1)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        lambda: (clear_config_cache(), asyncio.run(run_once())),
        trigger='interval',
        minutes=interval_minutes,
        max_instances=1,
        coalesce=True,
        id='job_hunter',
    )
    logger.info('Scheduler iniciado — intervalo: %d min', interval_minutes)
    try:
        asyncio.run(run_once())  # primera corrida inmediata
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info('Scheduler detenido.')


def main() -> int:
    parser = argparse.ArgumentParser(description='Job Hunter pipeline')
    parser.add_argument(
        '--once',
        action='store_true',
        help='Ejecuta un ciclo completo y termina.',
    )
    parser.add_argument(
        '--trial',
        action='store_true',
        help='Ciclo de prueba: 1 oferta por fuente por el flujo completo y termina.',
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        metavar='MINUTOS',
        help='Intervalo en minutos para el scheduler (default: 60).',
    )
    args = parser.parse_args()

    if args.trial:
        asyncio.run(run_trial())
        return 0

    if args.once:
        asyncio.run(run_once())
        return 0

    _run_scheduler(args.interval)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
