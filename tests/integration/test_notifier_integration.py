"""Integration: TelegramNotifier + MarkdownExporter against real services.

TelegramNotifier requires TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env.
MarkdownExporter writes to real disk (tmp_path).

Mark: pytest -m integration
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv(override=True)

import os
from datetime import date
from pathlib import Path

import pytest

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.notify.markdown_exporter import MarkdownExporter
from src.notify.telegram_notifier import TelegramNotifier, TelegramNotifierError

pytestmark = pytest.mark.integration


def _make_offer() -> Offer:
    return Offer(
        id='integ9abc123def456',
        fuente='elempleo',
        url='https://example.com/job/integ-test',
        titulo='Backend Python Developer',
        empresa='IntegCo',
        ubicacion='Remoto (Colombia)',
        posted_date=date(2024, 6, 1),
        descripcion_md=(
            '## Requisitos\n\nBuscamos desarrollador Python con experiencia en FastAPI, '
            'PostgreSQL y Docker. Trabajo 100% remoto.\n\n'
            '### Stack\n\nPython 3.10+, FastAPI, Docker, PostgreSQL.'
        ),
        skill_match=SkillMatch(
            skills_encontrados=['Python', 'FastAPI', 'Docker'],
            skills_faltantes=['Kubernetes'],
            fraccion=0.75,
            pasa=True,
        ),
        veredicto=MatchVerdict(
            score=0.88,
            apto=True,
            razon='Excelente match de stack técnico y modalidad remota',
            puntos_favor=['Python senior', 'FastAPI', 'Docker', 'Remoto'],
            puntos_contra=['No menciona Kubernetes'],
        ),
    )


# ---------------------------------------------------------------------------
# MarkdownExporter — real integration with disk
# ---------------------------------------------------------------------------

def test_markdown_exporter_writes_valid_file(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)

    assert path.exists()
    content = path.read_text(encoding='utf-8')

    # Frontmatter
    assert '---' in content
    assert 'id: integ9abc123def456' in content
    assert 'score: 0.88' in content
    assert 'apto: true' in content

    # Full description
    assert 'FastAPI, PostgreSQL y Docker' in content

    # Nombre de archivo con short_id
    assert 'integ9abc123' in path.name


def test_markdown_exporter_creates_nested_dir(tmp_path):
    nested = tmp_path / 'deep' / 'nested' / 'dir'
    exporter = MarkdownExporter(output_dir=str(nested))
    exporter.export(_make_offer())
    assert nested.exists()


# ---------------------------------------------------------------------------
# TelegramNotifier — real integration (only if credentials are available)
# ---------------------------------------------------------------------------

@pytest.fixture
def telegram_credentials():
    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        pytest.skip('TELEGRAM_TOKEN and TELEGRAM_CHAT_ID not configured in .env')
    return token, chat_id


def test_telegram_notifier_sends_message(telegram_credentials):
    token, chat_id = telegram_credentials
    notifier = TelegramNotifier(token=token, chat_id=chat_id)
    offer = _make_offer()
    # must not raise
    notifier.notify(offer)


def test_telegram_notifier_invalid_token_raises():
    notifier = TelegramNotifier(token='token_invalido_123', chat_id='000')
    offer = _make_offer()
    with pytest.raises(TelegramNotifierError):
        notifier.notify(offer)
