"""E2E integration: PipelineGraph with real Ollama and Telegram.

Requires:
  - Ollama running on localhost:11434 with nomic-embed-text and deepseek-r1:14b
  - Profile indexed in data/test_lancedb_e2e/perfil (indexed in the test)
  - TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env (optional)

Mark: pytest -m integration
Run:
    uv run pytest tests/integration/test_pipeline_e2e.py -v -s -m integration
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

import pytest

from src.core.db import SQLiteOfferRepository
from src.core.models import Offer
from src.core.normalize import OfferNormalizer
from src.embeddings.ollama_embedder import OllamaEmbedder
from src.embeddings.vector_store import LanceDbStore
from src.filters.date_filter import DateFilter
from src.filters.language import LanguageFilter
from src.filters.skill_filter import SkillFilter
from src.graph.pipeline import PipelineGraph
from src.judge.ollama_judge import OllamaJudge
from src.judge.profile_indexer import ProfileIndexer
from src.notify.markdown_exporter import MarkdownExporter

pytestmark = pytest.mark.integration

OLLAMA_URL = 'http://localhost:11434'
EMBED_MODEL = 'nomic-embed-text'
JUDGE_MODEL = 'deepseek-r1:14b'
TEST_DB_PATH = 'data/test_lancedb_e2e'

PROFILE_TEXT = """\
# Perfil profesional

Desarrollador backend con 4 años de experiencia en Python, FastAPI y Docker.
Familiarizado con arquitecturas de microservicios y despliegues en AWS.

## Skills
Python, FastAPI, Docker, PostgreSQL, AWS, Git

## Experiencia
- 3 años desarrollando APIs REST con FastAPI y Pydantic
- Automatización de pipelines de datos con Python y pandas
"""

RAW_OFFER_MATCH = {
    'url': 'https://linkedin.com/jobs/view/e2e-match-001',
    'titulo': 'Backend Python Developer',
    'empresa': 'TechCorp',
    'ubicacion': 'Bogotá, Colombia',
    'descripcion_md': (
        'Buscamos desarrollador backend con experiencia en Python y FastAPI. '
        'El rol incluye diseño de APIs REST, integración con Docker y despliegue en AWS. '
        'Requisitos: Python avanzado, FastAPI, Docker, AWS, PostgreSQL. '
        'Ofrecemos trabajo remoto, buen salario y crecimiento técnico.'
    ),
    'posted_date': date.today().isoformat(),
    'extraction_status': 'ok',
}

RAW_OFFER_OLD = {
    'url': 'https://linkedin.com/jobs/view/e2e-old-001',
    'titulo': 'Java Developer (antigua)',
    'empresa': 'OldCorp',
    'ubicacion': 'Medellín',
    'descripcion_md': 'Java Spring Boot developer needed for fintech project.',
    'posted_date': '2020-01-01',
    'extraction_status': 'ok',
}


@pytest.fixture(scope='module')
def tmp_dirs():
    db_dir = tempfile.mkdtemp(prefix='hunter_e2e_db_')
    out_dir = tempfile.mkdtemp(prefix='hunter_e2e_md_')
    yield db_dir, out_dir
    shutil.rmtree(db_dir, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)


@pytest.fixture(scope='module')
def pipeline(tmp_dirs):
    db_dir, out_dir = tmp_dirs
    db_path = str(Path(db_dir) / 'jobs.db')

    embedder = OllamaEmbedder(base_url=OLLAMA_URL, model=EMBED_MODEL)
    store = LanceDbStore(path=TEST_DB_PATH, embedder=embedder)

    # Indexar el perfil de prueba
    indexer = ProfileIndexer(store=store)
    indexer.index(PROFILE_TEXT)

    repo = SQLiteOfferRepository(db_path=db_path)
    judge = OllamaJudge(
        store=store,
        base_url=OLLAMA_URL,
        model=JUDGE_MODEL,
        top_k_profile=2,
        truncar_chars=2000,
        timeout_s=180.0,
    )
    exporter = MarkdownExporter(output_dir=out_dir)

    return PipelineGraph(
        repo=repo,
        normalizer=OfferNormalizer(),
        date_filter=DateFilter(max_days=30),
        lang_filter=LanguageFilter(idiomas_permitidos=['ES', 'EN']),
        skill_filter=SkillFilter(required_skills=['Python', 'FastAPI', 'Docker'], umbral_match=0.5),
        embedder=embedder,
        store=store,
        judge=judge,
        notifier=None,  # Telegram disabled in the base integration suite
        exporter=exporter,
        umbral_similitud=0.3,
        namespace_ofertas='ofertas_e2e',
    )


@pytest.mark.integration
def test_e2e_old_offer_is_rejected(pipeline) -> None:
    result = pipeline.process(RAW_OFFER_OLD, 'linkedin')
    assert result.estado_final == 'old', f'Expected old, got: {result.estado_final}'


@pytest.mark.integration
def test_e2e_matching_offer_produces_md_file(pipeline, tmp_dirs) -> None:
    _, out_dir = tmp_dirs
    result = pipeline.process(RAW_OFFER_MATCH, 'linkedin')

    # Bug K fix: 'matched' is no longer a valid notification state.
    # A notified pipeline ends in 'notified'; if the judge fails it ends in 'low_sim'.
    assert result.estado_final == 'notified', (
        f'Expected notified; got {result.estado_final}. '
        f'Check that Ollama is running and the profile is indexed.'
    )

    md_files = list(Path(out_dir).glob('*.md'))
    assert len(md_files) >= 1, 'Expected at least one .md file exported'
    content = md_files[0].read_text(encoding='utf-8')
    assert 'Python' in content


@pytest.mark.integration
def test_e2e_duplicate_is_silently_skipped(pipeline) -> None:
    # Second call with the same already-processed offer
    result = pipeline.process(RAW_OFFER_MATCH, 'linkedin')
    assert result.skipped is True
    assert result.estado_final == 'duplicate'


@pytest.mark.integration
def test_e2e_status_counts_are_persisted(pipeline) -> None:
    counts = pipeline.repo.count_by_status()
    assert isinstance(counts, dict)
    # At least the 'old' state from the previous test must be present
    total = sum(counts.values())
    assert total >= 1


@pytest.mark.integration
def test_e2e_judge_error_does_not_produce_matched_state(pipeline) -> None:
    """Bug K E2E: OllamaJudgeError must not result in state 'matched'."""
    from unittest.mock import patch
    from src.judge.ollama_judge import OllamaJudgeError

    raw = {**RAW_OFFER_MATCH, 'url': 'https://linkedin.com/jobs/view/e2e-judge-err-001'}

    with patch.object(pipeline.judge, 'judge', side_effect=OllamaJudgeError('forced')):
        result = pipeline.process(raw, 'linkedin')

    assert result.estado_final != 'matched', (
        "Bug K not fixed: OllamaJudgeError stored 'matched' instead of 'low_sim'"
    )
    assert result.estado_final == 'low_sim'
