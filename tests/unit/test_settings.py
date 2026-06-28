from pathlib import Path

import pytest
from pydantic import ValidationError

from src.settings import ProfileLoader, SettingsLoader, clear_config_cache, get_config


VALID_YAML = """
busquedas:
  elempleo:
    - cargo: "desarrollador python"
      ciudad: "bogota"
  linkedin:
    - cargo: "python developer"
      ubicacion: "Colombia"
skills:
  lista: ["Python", "FastAPI", "SQL"]
  umbral_match: 0.5
modelos:
  ollama_base_url: "http://localhost:11434"
  embeddings: "nomic-embed-text"
  juez: "deepseek-r1:14b"
filtros:
  max_days: 7
  idiomas_permitidos: ["es", "en"]
  umbral_similitud: 0.75
  truncar_descripcion_chars: 4000
vectores:
  path: "data/lancedb"
  namespace_perfil: "perfil"
  namespace_ofertas: "ofertas"
notificacion:
  telegram_habilitado: true
salidas:
  markdown_dir: "data/matches"
"""


def write_file(path: Path, content: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content, encoding='utf-8')


def test_settings_loader_reads_yaml_and_env(tmp_path: Path) -> None:
  settings_path = tmp_path / 'config' / 'settings.yaml'
  env_path = tmp_path / '.env'
  write_file(settings_path, VALID_YAML)
  write_file(env_path, 'TELEGRAM_TOKEN=test-token\nTELEGRAM_CHAT_ID=123\n')

  config = SettingsLoader(str(settings_path), str(env_path)).load()

  assert config.skills.lista == ['Python', 'FastAPI', 'SQL']
  assert config.skills.umbral_match == 0.5
  assert config.filtros.idiomas_permitidos == ['ES', 'EN']
  assert config.notificacion.telegram_token == 'test-token'
  assert config.notificacion.telegram_chat_id == '123'


def test_settings_loader_rejects_out_of_range_threshold(tmp_path: Path) -> None:
  settings_path = tmp_path / 'config' / 'settings.yaml'
  env_path = tmp_path / '.env'
  write_file(settings_path, VALID_YAML.replace('umbral_match: 0.5', 'umbral_match: 1.5'))
  write_file(env_path, 'TELEGRAM_TOKEN=test-token\nTELEGRAM_CHAT_ID=123\n')

  with pytest.raises(ValidationError):
    SettingsLoader(str(settings_path), str(env_path)).load()


def test_settings_loader_rejects_empty_skill_list(tmp_path: Path) -> None:
  settings_path = tmp_path / 'config' / 'settings.yaml'
  env_path = tmp_path / '.env'
  write_file(settings_path, VALID_YAML.replace('["Python", "FastAPI", "SQL"]', '[]'))
  write_file(env_path, 'TELEGRAM_TOKEN=test-token\nTELEGRAM_CHAT_ID=123\n')

  with pytest.raises(ValidationError, match='skills.lista no puede estar vacia'):
    SettingsLoader(str(settings_path), str(env_path)).load()


def test_settings_loader_requires_telegram_secrets_if_enabled(tmp_path: Path) -> None:
  settings_path = tmp_path / 'config' / 'settings.yaml'
  env_path = tmp_path / '.env'
  write_file(settings_path, VALID_YAML)
  write_file(env_path, '')

  with pytest.raises(ValidationError, match='TELEGRAM_TOKEN es obligatorio'):
    SettingsLoader(str(settings_path), str(env_path)).load()


def test_get_config_is_cached(tmp_path: Path) -> None:
  clear_config_cache()
  settings_path = tmp_path / 'config' / 'settings.yaml'
  env_path = tmp_path / '.env'
  write_file(settings_path, VALID_YAML)
  write_file(env_path, 'TELEGRAM_TOKEN=test-token\nTELEGRAM_CHAT_ID=123\n')

  cfg_1 = get_config(str(settings_path), str(env_path))
  cfg_2 = get_config(str(settings_path), str(env_path))

  assert cfg_1 is cfg_2


def test_profile_loader_reads_non_empty_text(tmp_path: Path) -> None:
  profile_path = tmp_path / 'config' / 'profile.md'
  write_file(profile_path, '# Perfil\nPython backend')

  profile_text = ProfileLoader(str(profile_path)).load()

  assert 'Python backend' in profile_text

