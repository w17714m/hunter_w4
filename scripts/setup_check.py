"""scripts/setup_check.py — Environment check before running the pipeline.

Usage:
    uv run python scripts/setup_check.py

Exits with code 0 if there are no critical failures (fail), 1 if there is at least one.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
import lancedb
import pyarrow as pa

# Add the project root to the path to import src.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.loaders import get_config
from src.config.schemas import AppConfig


CheckEstado = Literal['ok', 'warn', 'fail']

_PLACEHOLDER_MARKERS = ('describe aqui', 'describe here')
_PROFILE_MIN_CHARS = 50

_ICON = {'ok': '✅', 'warn': '⚠️ ', 'fail': '❌'}


@dataclass
class CheckResult:
    nombre: str
    estado: CheckEstado
    mensaje: str
    accion: str | None = None


class EnvironmentChecker:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def run_all(self) -> list[CheckResult]:
        checks = [
            self.check_ollama,
            self.check_ollama_models,
            self.check_telegram,
            self.check_chromium,
            self.check_linkedin_profile,
            self.check_lancedb,
            self.check_matches_dir,
            self.check_skills_config,
            self.check_profile_md,
        ]
        results: list[CheckResult] = []
        for check_fn in checks:
            nombre = getattr(check_fn, '__name__', str(check_fn)).replace('check_', '')
            try:
                results.append(check_fn())
            except Exception as exc:
                results.append(CheckResult(
                    nombre=nombre,
                    estado='fail',
                    mensaje=f'Error inesperado: {exc}',
                ))
        return results

    # ------------------------------------------------------------------
    # Checks individuales
    # ------------------------------------------------------------------

    def check_ollama(self) -> CheckResult:
        url = f'{self._cfg.modelos.ollama_base_url}/api/tags'
        try:
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 200:
                return CheckResult('Ollama', 'ok', f'respondiendo en {self._cfg.modelos.ollama_base_url}')
            return CheckResult(
                'Ollama', 'fail',
                f'HTTP {resp.status_code} en {url}',
                accion=f'Verify Ollama is running at {self._cfg.modelos.ollama_base_url}',
            )
        except httpx.TransportError as exc:
            return CheckResult(
                'Ollama', 'fail',
                f'No se pudo conectar: {exc}',
                accion=f'Iniciar Ollama: ollama serve  (esperado en {self._cfg.modelos.ollama_base_url})',
            )

    def check_ollama_models(self) -> CheckResult:
        url = f'{self._cfg.modelos.ollama_base_url}/api/tags'
        try:
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code != 200:
                return CheckResult(
                    'Modelos Ollama', 'fail',
                    'Ollama no disponible — no se pueden verificar modelos',
                )
            data = resp.json()
            available = {m['name'] for m in data.get('models', [])}
            needed = {
                self._cfg.modelos.embeddings: 'embeddings',
                self._cfg.modelos.juez: 'juez',
            }
            missing = [label for model, label in needed.items() if not any(
                a == model or a.startswith(f'{model}:') for a in available
            )]
            if not missing:
                embed = self._cfg.modelos.embeddings
                judge = self._cfg.modelos.juez
                return CheckResult('Modelos Ollama', 'ok', f'{embed} ✓  {judge} ✓')
            faltantes = ', '.join(missing)
            return CheckResult(
                'Modelos Ollama', 'warn',
                f'Modelos faltantes: {faltantes}',
                accion=f'Descargar con: ollama pull {self._cfg.modelos.embeddings}  /  ollama pull {self._cfg.modelos.juez}',
            )
        except httpx.TransportError as exc:
            return CheckResult('Modelos Ollama', 'fail', f'No se pudo conectar: {exc}')

    def check_telegram(self) -> CheckResult:
        token = self._cfg.notificacion.telegram_token
        chat_id = self._cfg.notificacion.telegram_chat_id
        habilitado = self._cfg.notificacion.telegram_habilitado

        if not habilitado:
            return CheckResult('Telegram', 'warn', 'Telegram deshabilitado en config')

        if not token or not chat_id:
            return CheckResult(
                'Telegram', 'fail',
                'Credenciales no configuradas',
                accion='Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env',
            )
        url = f'https://api.telegram.org/bot{token}/getMe'
        try:
            resp = httpx.get(url, timeout=10.0)
            data = resp.json()
            if resp.status_code == 200 and data.get('ok'):
                bot_name = data.get('result', {}).get('username', 'bot')
                return CheckResult('Telegram', 'ok', f'Bot activo: @{bot_name}')
            return CheckResult(
                'Telegram', 'fail',
                f'Invalid token (HTTP {resp.status_code})',
                accion='Verificar TELEGRAM_TOKEN en .env',
            )
        except httpx.TransportError as exc:
            return CheckResult('Telegram', 'fail', f'Error de red: {exc}')

    def check_chromium(self) -> CheckResult:
        return asyncio.run(self._check_chromium_async())

    async def _check_chromium_async(self) -> CheckResult:
        try:
            from playwright.async_api import async_playwright, Error as PlaywrightError
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.launch(headless=True)
                await browser.close()
            finally:
                await pw.stop()
            return CheckResult('Chromium', 'ok', 'Playwright + Chromium listos')
        except Exception as exc:
            msg = str(exc)
            if 'Executable doesn' in msg or 'playwright install' in msg:
                return CheckResult(
                    'Chromium', 'fail',
                    'PLAYWRIGHT_BROWSER_MISSING',
                    accion='Instalar Chromium: uv run playwright install chromium',
                )
            return CheckResult('Chromium', 'fail', f'Error al lanzar Chromium: {msg[:120]}')

    def check_linkedin_profile(self) -> CheckResult:
        profile_dir = Path('data/playwright/linkedin-profile')
        if not profile_dir.exists():
            return CheckResult(
                'Perfil LinkedIn', 'warn',
                f'{profile_dir}/ no existe',
                accion='Ejecutar: uv run python scripts/login_linkedin_persistent.py',
            )
        archivos = list(profile_dir.iterdir())
        if not archivos:
            return CheckResult(
                'Perfil LinkedIn', 'warn',
                f'{profile_dir}/ exists but is empty',
                accion='Ejecutar: uv run python scripts/login_linkedin_persistent.py',
            )
        return CheckResult('Perfil LinkedIn', 'ok', f'{profile_dir}/ con {len(archivos)} archivo(s)')

    def check_lancedb(self) -> CheckResult:
        tmp_ns = f'_check_{uuid.uuid4().hex[:8]}'
        db_path = Path(self._cfg.vectores.path)
        try:
            db_path.mkdir(parents=True, exist_ok=True)
            db = lancedb.connect(str(db_path))
            schema = pa.schema([
                pa.field('id', pa.string()),
                pa.field('text', pa.string()),
            ])
            table = db.create_table(tmp_ns, schema=schema)
            table.add([{'id': 'chk', 'text': 'check'}])
            count = table.count_rows()
            db.drop_table(tmp_ns)
            if count >= 1:
                return CheckResult('LanceDB', 'ok', f'escritura y limpieza OK en {db_path}')
            return CheckResult('LanceDB', 'fail', 'Write returned count=0')
        except Exception as exc:
            return CheckResult(
                'LanceDB', 'fail',
                f'Error de I/O: {exc}',
                accion=f'Verificar permisos en {db_path}',
            )

    def check_matches_dir(self) -> CheckResult:
        output_dir = Path(self._cfg.salidas.markdown_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            tmp = output_dir / f'_check_{uuid.uuid4().hex[:8]}.tmp'
            tmp.write_text('ok', encoding='utf-8')
            tmp.unlink()
            return CheckResult('Directorio matches', 'ok', f'{output_dir}/ existe y es escribible')
        except OSError as exc:
            return CheckResult(
                'Directorio matches', 'fail',
                f'No se puede escribir en {output_dir}: {exc}',
                accion=f'Verificar permisos del directorio {output_dir}',
            )

    def check_skills_config(self) -> CheckResult:
        skills = self._cfg.skills.lista
        umbral = self._cfg.skills.umbral_match
        if not skills:
            return CheckResult(
                'Config skills', 'fail',
                'skills.lista is empty',
                accion='Add at least one skill in config/settings.yaml → skills.lista',
            )
        if not (0.0 <= umbral <= 1.0):
            return CheckResult(
                'Config skills', 'fail',
                f'umbral_match={umbral} fuera de rango [0.0–1.0]',
                accion='Corregir skills.umbral_match en config/settings.yaml',
            )
        return CheckResult(
            'Config skills', 'ok',
            f'{len(skills)} skill(s), umbral={umbral}',
        )

    def check_profile_md(self) -> CheckResult:
        profile_path = Path('config/profile.md')
        if not profile_path.exists():
            return CheckResult(
                'profile.md', 'fail',
                'config/profile.md no existe',
                accion='Crear config/profile.md con tu perfil profesional',
            )
        text = profile_path.read_text(encoding='utf-8').strip()
        if not text:
            return CheckResult(
                'profile.md', 'warn',
                'config/profile.md is empty',
                accion='Escribir tu perfil profesional en config/profile.md',
            )
        lower = text.lower()
        is_placeholder = (
            any(marker in lower for marker in _PLACEHOLDER_MARKERS)
            or len(text) < _PROFILE_MIN_CHARS
        )
        if is_placeholder:
            return CheckResult(
                'profile.md', 'warn',
                'Contains placeholder text — the LLM judge will have no real context',
                accion='Editar config/profile.md con tu experiencia, stack y preferencias',
            )
        return CheckResult('profile.md', 'ok', f'{len(text)} chars — parece tener contenido real')


# ---------------------------------------------------------------------------
# Formato de reporte
# ---------------------------------------------------------------------------

def print_report(results: list[CheckResult]) -> None:
    width = 48
    print(f'\n{"=" * width}')
    print('  Job Hunter — Environment check')
    print(f'{"=" * width}\n')

    nombre_w = max(len(r.nombre) for r in results) + 2
    for r in results:
        icon = _ICON[r.estado]
        nombre = r.nombre.ljust(nombre_w)
        print(f'  {icon} {nombre}{r.mensaje}')
        if r.accion:
            print(f'     → {r.accion}')

    n_ok = sum(1 for r in results if r.estado == 'ok')
    n_warn = sum(1 for r in results if r.estado == 'warn')
    n_fail = sum(1 for r in results if r.estado == 'fail')

    print(f'\n{"=" * width}')
    print(f'  Resultado: {n_ok} ✅   {n_warn} ⚠️    {n_fail} ❌')
    if n_fail:
        print('  Critical failures found — fix before running the pipeline.')
    elif n_warn:
        print('  Advertencias presentes — el sistema puede correr con limitaciones.')
    else:
        print('  Environment ready for production.')
    print(f'{"=" * width}\n')


def main() -> int:
    try:
        cfg = get_config()
    except Exception as exc:
        print(f'\n❌ Failed to load configuration: {exc}')
        print('   → Verificar config/settings.yaml y .env\n')
        return 1

    checker = EnvironmentChecker(cfg)
    results = checker.run_all()
    print_report(results)
    return 1 if any(r.estado == 'fail' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
