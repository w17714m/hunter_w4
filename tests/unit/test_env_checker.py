"""Tests unitarios para EnvironmentChecker.

Todos los servicios externos se reemplazan con stubs/mocks.
No se requiere Ollama, Telegram, Playwright ni LanceDB reales.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Asegura que src/ sea importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.setup_check import CheckResult, EnvironmentChecker


# ---------------------------------------------------------------------------
# Fixture: AppConfig mínimo
# ---------------------------------------------------------------------------

def _make_cfg(
    *,
    ollama_url: str = 'http://localhost:11434',
    embed_model: str = 'nomic-embed-text',
    judge_model: str = 'deepseek-r1:14b',
    telegram_habilitado: bool = True,
    telegram_token: str | None = 'token123',
    telegram_chat_id: str | None = '999',
    skills: list[str] | None = None,
    umbral: float = 0.5,
    vector_path: str = 'data/lancedb',
    markdown_dir: str = 'data/matches',
) -> MagicMock:
    cfg = MagicMock()
    cfg.modelos.ollama_base_url = ollama_url
    cfg.modelos.embeddings = embed_model
    cfg.modelos.juez = judge_model
    cfg.notificacion.telegram_habilitado = telegram_habilitado
    cfg.notificacion.telegram_token = telegram_token
    cfg.notificacion.telegram_chat_id = telegram_chat_id
    cfg.skills.lista = skills if skills is not None else ['Python', 'FastAPI']
    cfg.skills.umbral_match = umbral
    cfg.vectores.path = vector_path
    cfg.salidas.markdown_dir = markdown_dir
    return cfg


# ---------------------------------------------------------------------------
# check_ollama
# ---------------------------------------------------------------------------

class TestCheckOllama:
    def test_ok_when_200(self) -> None:
        resp = MagicMock(status_code=200)
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_ollama()
        assert result.estado == 'ok'

    def test_fail_on_non_200(self) -> None:
        resp = MagicMock(status_code=503)
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_ollama()
        assert result.estado == 'fail'

    def test_fail_on_connection_error(self) -> None:
        import httpx
        with patch('scripts.setup_check.httpx.get', side_effect=httpx.TransportError('conn refused')):
            result = EnvironmentChecker(_make_cfg()).check_ollama()
        assert result.estado == 'fail'
        assert result.accion is not None


# ---------------------------------------------------------------------------
# check_ollama_models
# ---------------------------------------------------------------------------

class TestCheckOllamaModels:
    def _mock_tags(self, models: list[str]) -> MagicMock:
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'models': [{'name': m} for m in models]}
        return resp

    def test_ok_when_both_models_present(self) -> None:
        resp = self._mock_tags(['nomic-embed-text', 'deepseek-r1:14b'])
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_ollama_models()
        assert result.estado == 'ok'

    def test_warn_when_one_model_missing(self) -> None:
        resp = self._mock_tags(['nomic-embed-text'])  # falta el juez
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_ollama_models()
        assert result.estado == 'warn'
        assert result.accion is not None

    def test_fail_when_ollama_down(self) -> None:
        import httpx
        with patch('scripts.setup_check.httpx.get', side_effect=httpx.TransportError('down')):
            result = EnvironmentChecker(_make_cfg()).check_ollama_models()
        assert result.estado == 'fail'

    def test_model_name_prefix_match(self) -> None:
        # "nomic-embed-text:latest" debe coincidir con "nomic-embed-text"
        resp = self._mock_tags(['nomic-embed-text:latest', 'deepseek-r1:14b'])
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_ollama_models()
        assert result.estado == 'ok'


# ---------------------------------------------------------------------------
# check_telegram
# ---------------------------------------------------------------------------

class TestCheckTelegram:
    def test_ok_when_bot_responds(self) -> None:
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'ok': True, 'result': {'username': 'MyBot'}}
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_telegram()
        assert result.estado == 'ok'
        assert 'MyBot' in result.mensaje

    def test_fail_when_no_token(self) -> None:
        result = EnvironmentChecker(_make_cfg(telegram_token=None)).check_telegram()
        assert result.estado == 'fail'
        assert result.accion is not None

    def test_fail_when_no_chat_id(self) -> None:
        result = EnvironmentChecker(_make_cfg(telegram_chat_id=None)).check_telegram()
        assert result.estado == 'fail'

    def test_warn_when_disabled(self) -> None:
        result = EnvironmentChecker(_make_cfg(telegram_habilitado=False)).check_telegram()
        assert result.estado == 'warn'

    def test_fail_on_invalid_token(self) -> None:
        resp = MagicMock(status_code=401)
        resp.json.return_value = {'ok': False}
        with patch('scripts.setup_check.httpx.get', return_value=resp):
            result = EnvironmentChecker(_make_cfg()).check_telegram()
        assert result.estado == 'fail'


# ---------------------------------------------------------------------------
# check_chromium
# ---------------------------------------------------------------------------

class TestCheckChromium:
    def test_ok_when_playwright_launches(self) -> None:
        browser_mock = AsyncMock()
        pw_mock = AsyncMock()
        pw_mock.chromium.launch = AsyncMock(return_value=browser_mock)
        pw_ctx = AsyncMock()
        pw_ctx.__aenter__ = AsyncMock(return_value=pw_mock)

        with patch('scripts.setup_check.asyncio.run') as mock_run:
            mock_run.return_value = CheckResult('Chromium', 'ok', 'Playwright + Chromium listos')
            result = EnvironmentChecker(_make_cfg()).check_chromium()
        assert result.estado == 'ok'

    def test_fail_when_browser_missing(self) -> None:
        with patch('scripts.setup_check.asyncio.run') as mock_run:
            mock_run.return_value = CheckResult(
                'Chromium', 'fail',
                'PLAYWRIGHT_BROWSER_MISSING',
                accion='uv run playwright install chromium',
            )
            result = EnvironmentChecker(_make_cfg()).check_chromium()
        assert result.estado == 'fail'
        assert 'playwright install' in (result.accion or '')


# ---------------------------------------------------------------------------
# check_linkedin_profile
# ---------------------------------------------------------------------------

class TestCheckLinkedInProfile:
    def test_ok_when_profile_dir_has_files(self, tmp_path: Path) -> None:
        profile_dir = tmp_path / 'linkedin-profile'
        profile_dir.mkdir()
        (profile_dir / 'Default').mkdir()  # simula archivo de sesión

        with patch('scripts.setup_check.Path', side_effect=lambda p: tmp_path / Path(p).name if 'linkedin' in str(p) else Path(p)):
            checker = EnvironmentChecker(_make_cfg())
            # Llamamos directamente con el path real
            checker._cfg = _make_cfg()
            with patch.object(Path, 'exists', return_value=True), \
                 patch.object(Path, 'iterdir', return_value=iter([profile_dir / 'Default'])):
                result = checker.check_linkedin_profile()
        assert result.estado == 'ok'

    def test_warn_when_profile_dir_missing(self) -> None:
        with patch.object(Path, 'exists', return_value=False):
            result = EnvironmentChecker(_make_cfg()).check_linkedin_profile()
        assert result.estado == 'warn'
        assert result.accion is not None

    def test_warn_when_profile_dir_empty(self) -> None:
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'iterdir', return_value=iter([])):
            result = EnvironmentChecker(_make_cfg()).check_linkedin_profile()
        assert result.estado == 'warn'


# ---------------------------------------------------------------------------
# check_lancedb
# ---------------------------------------------------------------------------

class TestCheckLanceDB:
    def test_ok_when_write_succeeds(self) -> None:
        import scripts.setup_check as sc

        table_mock = MagicMock()
        table_mock.count_rows.return_value = 1
        db_mock = MagicMock()
        db_mock.create_table.return_value = table_mock

        with patch.object(sc.lancedb, 'connect', return_value=db_mock), \
             patch.object(Path, 'mkdir'):
            result = EnvironmentChecker(_make_cfg()).check_lancedb()
        assert result.estado == 'ok'
        db_mock.drop_table.assert_called_once()

    def test_fail_when_write_raises(self) -> None:
        import scripts.setup_check as sc

        with patch.object(sc.lancedb, 'connect', side_effect=OSError('permission denied')), \
             patch.object(Path, 'mkdir'):
            result = EnvironmentChecker(_make_cfg()).check_lancedb()
        assert result.estado == 'fail'
        assert result.accion is not None


# ---------------------------------------------------------------------------
# check_matches_dir
# ---------------------------------------------------------------------------

class TestCheckMatchesDir:
    def test_ok_when_writable(self, tmp_path: Path) -> None:
        cfg = _make_cfg(markdown_dir=str(tmp_path / 'matches'))
        result = EnvironmentChecker(cfg).check_matches_dir()
        assert result.estado == 'ok'

    def test_fail_when_not_writable(self) -> None:
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'write_text', side_effect=OSError('read-only')):
            result = EnvironmentChecker(_make_cfg()).check_matches_dir()
        assert result.estado == 'fail'


# ---------------------------------------------------------------------------
# check_skills_config
# ---------------------------------------------------------------------------

class TestCheckSkillsConfig:
    def test_ok_when_valid(self) -> None:
        result = EnvironmentChecker(_make_cfg(skills=['Python', 'Docker'], umbral=0.5)).check_skills_config()
        assert result.estado == 'ok'
        assert '2' in result.mensaje

    def test_fail_when_empty_list(self) -> None:
        result = EnvironmentChecker(_make_cfg(skills=[])).check_skills_config()
        assert result.estado == 'fail'
        assert result.accion is not None

    def test_fail_when_umbral_out_of_range(self) -> None:
        result = EnvironmentChecker(_make_cfg(umbral=1.5)).check_skills_config()
        assert result.estado == 'fail'


# ---------------------------------------------------------------------------
# check_profile_md
# ---------------------------------------------------------------------------

class TestCheckProfileMd:
    def test_ok_when_real_content(self, tmp_path: Path) -> None:
        profile = tmp_path / 'profile.md'
        profile.write_text(
            '# Perfil\n\nDesarrollador Python con 5 años de experiencia en FastAPI y Docker.\n'
            'Trabajo en equipos ágiles y tengo experiencia en AWS y microservicios.',
            encoding='utf-8',
        )
        with patch('scripts.setup_check.Path', side_effect=lambda p: profile if 'profile.md' in str(p) else Path(p)):
            checker = EnvironmentChecker(_make_cfg())
            with patch.object(Path, 'exists', return_value=True), \
                 patch.object(Path, 'read_text', return_value=profile.read_text(encoding='utf-8')):
                result = checker.check_profile_md()
        assert result.estado == 'ok'

    def test_warn_when_placeholder_text(self) -> None:
        placeholder = 'Describe aqui tu experiencia, stack principal, tipos de rol objetivo.'
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', return_value=placeholder):
            result = EnvironmentChecker(_make_cfg()).check_profile_md()
        assert result.estado == 'warn'
        assert result.accion is not None

    def test_warn_when_too_short(self) -> None:
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', return_value='Hola'):
            result = EnvironmentChecker(_make_cfg()).check_profile_md()
        assert result.estado == 'warn'

    def test_fail_when_file_missing(self) -> None:
        with patch.object(Path, 'exists', return_value=False):
            result = EnvironmentChecker(_make_cfg()).check_profile_md()
        assert result.estado == 'fail'


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_run_all_returns_nine_results(self) -> None:
        checker = EnvironmentChecker(_make_cfg())
        # Parchamos todos los checks para que no hagan I/O real
        dummy = CheckResult('x', 'ok', 'stub')
        with patch.object(checker, 'check_ollama', return_value=dummy), \
             patch.object(checker, 'check_ollama_models', return_value=dummy), \
             patch.object(checker, 'check_telegram', return_value=dummy), \
             patch.object(checker, 'check_chromium', return_value=dummy), \
             patch.object(checker, 'check_linkedin_profile', return_value=dummy), \
             patch.object(checker, 'check_lancedb', return_value=dummy), \
             patch.object(checker, 'check_matches_dir', return_value=dummy), \
             patch.object(checker, 'check_skills_config', return_value=dummy), \
             patch.object(checker, 'check_profile_md', return_value=dummy):
            results = checker.run_all()
        assert len(results) == 9

    def test_run_all_continues_when_one_check_raises(self) -> None:
        checker = EnvironmentChecker(_make_cfg())
        dummy = CheckResult('x', 'ok', 'stub')

        # Reemplazamos check_ollama con una función que tiene __name__ y explota
        original_ollama = checker.check_ollama

        def check_ollama_explode() -> CheckResult:  # nombre intencionado para getattr
            raise RuntimeError('boom')

        checker.check_ollama = check_ollama_explode  # type: ignore[method-assign]

        with patch.object(checker, 'check_ollama_models', return_value=dummy), \
             patch.object(checker, 'check_telegram', return_value=dummy), \
             patch.object(checker, 'check_chromium', return_value=dummy), \
             patch.object(checker, 'check_linkedin_profile', return_value=dummy), \
             patch.object(checker, 'check_lancedb', return_value=dummy), \
             patch.object(checker, 'check_matches_dir', return_value=dummy), \
             patch.object(checker, 'check_skills_config', return_value=dummy), \
             patch.object(checker, 'check_profile_md', return_value=dummy):
            results = checker.run_all()

        checker.check_ollama = original_ollama  # type: ignore[method-assign]

        assert len(results) == 9
        # El check que explotó debe reportarse como fail
        failed = [r for r in results if r.estado == 'fail']
        assert len(failed) == 1
        assert 'boom' in failed[0].mensaje
