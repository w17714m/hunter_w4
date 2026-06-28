from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from src.core.models import Offer

logger = logging.getLogger(__name__)

_FRONTMATTER_TEMPLATE = """\
---
id: {id}
fuente: {fuente}
url: {url}
titulo: {titulo}
empresa: {empresa}
ubicacion: {ubicacion}
fecha_oferta: {fecha_oferta}
fecha_match: {fecha_match}
score: {score}
apto: {apto}
skills_encontrados: {skills_encontrados}
skills_faltantes: {skills_faltantes}
fraccion_skills: {fraccion_skills}
---\
"""

_BODY_TEMPLATE = """\

# {titulo}

**Empresa:** {empresa}
**Ubicación:** {ubicacion}
**Fuente:** [{fuente}]({url})

## Evaluación del juez

**Score:** {score}
**Razón:** {razon}

### Puntos a favor

{puntos_favor}

### Puntos en contra

{puntos_contra}

## Skills

| Encontrados | Faltantes |
|-------------|-----------|
| {skills_encontrados_str} | {skills_faltantes_str} |

## Descripción original

{descripcion_md}
"""


def _slug(text: str) -> str:
    """Convierte un texto en un slug de hasta 40 chars apto para nombres de archivo."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text).strip('-')
    return text[:40]


def _bullet_list(items: list[str]) -> str:
    if not items:
        return '—'
    return '\n'.join(f'- {item}' for item in items)


class MarkdownExporterError(Exception):
    pass


class MarkdownExporter:
    """Escribe un archivo .md por cada oferta que superó el match.

    Nombre: {YYYY-MM-DD}_{offer.id[:12]}_{slug_titulo}.md
    El directorio se crea automáticamente si no existe.
    """

    def __init__(self, output_dir: str = 'data/matches') -> None:
        self.output_dir = Path(output_dir)

    def export(self, offer: Offer) -> Path:
        """Escribe el archivo y retorna su Path. Lanza MarkdownExporterError en fallo."""
        if offer.veredicto is None:
            raise MarkdownExporterError(
                f'La oferta {offer.id[:12]} no tiene veredicto; no se puede exportar.'
            )
        if offer.skill_match is None:
            raise MarkdownExporterError(
                f'La oferta {offer.id[:12]} no tiene skill_match; no se puede exportar.'
            )

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MarkdownExporterError(
                f'No se pudo crear el directorio {self.output_dir}: {exc}'
            ) from exc

        filename = self._build_filename(offer)
        path = self.output_dir / filename
        content = self._build_content(offer)

        try:
            path.write_text(content, encoding='utf-8')
        except OSError as exc:
            raise MarkdownExporterError(f'No se pudo escribir {path}: {exc}') from exc

        logger.info('Oferta exportada: %s', path)
        return path

    def _build_filename(self, offer: Offer) -> str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        short_id = offer.id[:12]
        titulo_slug = _slug(offer.titulo)
        return f'{date_str}_{short_id}_{titulo_slug}.md'

    def _build_content(self, offer: Offer) -> str:
        veredicto = offer.veredicto
        skill_match = offer.skill_match
        fecha_match = datetime.now().isoformat()

        frontmatter = _FRONTMATTER_TEMPLATE.format(
            id=offer.id,
            fuente=offer.fuente,
            url=offer.url,
            titulo=offer.titulo,
            empresa=offer.empresa or '',
            ubicacion=offer.ubicacion or '',
            fecha_oferta=str(offer.posted_date) if offer.posted_date else '',
            fecha_match=fecha_match,
            score=veredicto.score,
            apto=str(veredicto.apto).lower(),
            skills_encontrados=skill_match.skills_encontrados,
            skills_faltantes=skill_match.skills_faltantes,
            fraccion_skills=skill_match.fraccion,
        )

        body = _BODY_TEMPLATE.format(
            titulo=offer.titulo,
            empresa=offer.empresa or 'No especificada',
            ubicacion=offer.ubicacion or 'No especificada',
            fuente=offer.fuente,
            url=offer.url,
            score=f'{veredicto.score:.0%}',
            razon=veredicto.razon,
            puntos_favor=_bullet_list(veredicto.puntos_favor),
            puntos_contra=_bullet_list(veredicto.puntos_contra),
            skills_encontrados_str=', '.join(skill_match.skills_encontrados) or '—',
            skills_faltantes_str=', '.join(skill_match.skills_faltantes) or '—',
            descripcion_md=offer.descripcion_md,
        )

        return frontmatter + body
