from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from src.core.models import MatchVerdict, Offer, SkillMatch
from src.notify.markdown_exporter import (
    MarkdownExporter,
    MarkdownExporterError,
    _bullet_list,
    _slug,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_offer(
    titulo: str = 'Backend Developer Python',
    empresa: str | None = 'TechCo',
    ubicacion: str | None = 'Bogotá',
    posted_date: date | None = date(2024, 6, 1),
    veredicto: MatchVerdict | None = None,
    skill_match: SkillMatch | None = None,
) -> Offer:
    sm = skill_match or SkillMatch(
        skills_encontrados=['Python', 'Docker'],
        skills_faltantes=['Java'],
        fraccion=0.7,
        pasa=True,
    )
    v = veredicto or MatchVerdict(
        score=0.85,
        apto=True,
        razon='Buen perfil',
        puntos_favor=['Python senior'],
        puntos_contra=['Sin Java'],
    )
    return Offer(
        id='abc123def456789full',
        fuente='elempleo',
        url='https://example.com/job/1',
        titulo=titulo,
        empresa=empresa,
        ubicacion=ubicacion,
        posted_date=posted_date,
        descripcion_md='## Requisitos\n\nPython 3.10, Docker.',
        skill_match=sm,
        veredicto=v,
    )


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------

def test_slug_basic():
    assert _slug('Backend Developer') == 'backend-developer'


def test_slug_removes_special_chars():
    assert _slug('C++ / Python: Dev') == 'c-python-dev'


def test_slug_truncates_to_40():
    long = 'a' * 60
    assert len(_slug(long)) <= 40


def test_slug_no_leading_trailing_dashes():
    result = _slug('  spaces  ')
    assert not result.startswith('-')
    assert not result.endswith('-')


# ---------------------------------------------------------------------------
# _bullet_list
# ---------------------------------------------------------------------------

def test_bullet_list_with_items():
    result = _bullet_list(['A', 'B', 'C'])
    assert result == '- A\n- B\n- C'


def test_bullet_list_empty():
    assert _bullet_list([]) == '—'


# ---------------------------------------------------------------------------
# MarkdownExporter — nombre de archivo
# ---------------------------------------------------------------------------

def test_filename_format(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    filename = exporter._build_filename(offer)

    # Formato: YYYY-MM-DD_<12chars>_<slug>.md
    assert re.match(r'\d{4}-\d{2}-\d{2}_abc123def456_', filename)
    assert filename.endswith('.md')


def test_filename_slug_from_titulo(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer(titulo='Senior Python Engineer')
    filename = exporter._build_filename(offer)
    assert 'senior-python-engineer' in filename


# ---------------------------------------------------------------------------
# MarkdownExporter — contenido del archivo
# ---------------------------------------------------------------------------

def test_export_creates_file(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)

    assert path.exists()
    assert path.suffix == '.md'


def test_export_creates_directory_if_missing(tmp_path):
    subdir = tmp_path / 'a' / 'b' / 'c'
    exporter = MarkdownExporter(output_dir=str(subdir))
    offer = _make_offer()
    exporter.export(offer)
    assert subdir.exists()


def test_export_frontmatter_contains_full_id(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert 'id: abc123def456789full' in content


def test_export_frontmatter_contains_score_and_apto(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert 'score: 0.85' in content
    assert 'apto: true' in content


def test_export_frontmatter_contains_skills(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert 'Python' in content
    assert 'Java' in content


def test_export_body_contains_descripcion_md(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert '## Descripción original' in content
    assert offer.descripcion_md in content


def test_export_body_contains_puntos_favor_contra(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert '- Python senior' in content
    assert '- Sin Java' in content


def test_export_empresa_none_shows_fallback(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer(empresa=None)
    path = exporter.export(offer)
    content = path.read_text(encoding='utf-8')

    assert 'No especificada' in content


def test_export_without_veredicto_raises(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    offer.veredicto = None

    with pytest.raises(MarkdownExporterError, match='veredicto'):
        exporter.export(offer)


def test_export_without_skill_match_raises(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    offer.skill_match = None

    with pytest.raises(MarkdownExporterError, match='skill_match'):
        exporter.export(offer)


def test_export_returns_path_object(tmp_path):
    exporter = MarkdownExporter(output_dir=str(tmp_path))
    offer = _make_offer()
    result = exporter.export(offer)

    assert isinstance(result, Path)
