from __future__ import annotations

from functools import lru_cache
from os import getenv
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from src.config.schemas import AppConfig


class SettingsLoader:
  def __init__(self, settings_path: str = 'config/settings.yaml', env_path: str = '.env') -> None:
    self.settings_path = Path(settings_path)
    self.env_path = Path(env_path)

  def load(self) -> AppConfig:
    env_values: dict[str, str | None] = {}
    env_loaded_from_file = self.env_path.exists()
    if env_loaded_from_file:
      raw_env = dotenv_values(self.env_path)
      env_values = {str(key): value for key, value in raw_env.items()}

    raw = self._read_yaml(self.settings_path)
    notificacion = dict(raw.get('notificacion') or {})
    notificacion['telegram_token'] = self._read_env(
      'TELEGRAM_TOKEN',
      env_values=env_values,
      env_loaded_from_file=env_loaded_from_file,
    )
    notificacion['telegram_chat_id'] = self._read_env(
      'TELEGRAM_CHAT_ID',
      env_values=env_values,
      env_loaded_from_file=env_loaded_from_file,
    )
    raw['notificacion'] = notificacion

    fuentes = dict(raw.get('fuentes') or {})
    for env_key, config_key, default in (
      ('LINKEDIN_BASE_URL', 'linkedin_base_url', 'https://www.linkedin.com'),
      ('ELEMPLEO_BASE_URL', 'elempleo_base_url', 'https://www.elempleo.com'),
      ('COMPUTRABAJO_BASE_URL', 'computrabajo_base_url', 'https://co.computrabajo.com'),
    ):
      value = self._read_env(env_key, env_values=env_values, env_loaded_from_file=env_loaded_from_file)
      if value:
        fuentes[config_key] = value
      elif config_key not in fuentes:
        fuentes[config_key] = default
    raw['fuentes'] = fuentes

    return AppConfig.model_validate(raw)

  @staticmethod
  def _read_env(name: str, env_values: dict[str, str | None], env_loaded_from_file: bool) -> str | None:
    value = env_values.get(name) if env_loaded_from_file else getenv(name)
    if value is None:
      return None
    stripped = value.strip()
    return stripped if stripped else None

  @staticmethod
  def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
      raise FileNotFoundError(f'No existe archivo de configuracion: {path}')

    with path.open('r', encoding='utf-8') as stream:
      data = yaml.safe_load(stream) or {}

    if not isinstance(data, dict):
      raise ValueError('config/settings.yaml debe contener un objeto YAML en la raiz')
    return data


class ProfileLoader:
  def __init__(self, profile_path: str = 'config/profile.md') -> None:
    self.profile_path = Path(profile_path)

  def load(self) -> str:
    if not self.profile_path.exists():
      raise FileNotFoundError(f'No existe perfil profesional: {self.profile_path}')
    text = self.profile_path.read_text(encoding='utf-8').strip()
    if not text:
      raise ValueError('config/profile.md no puede estar vacio')
    return text


@lru_cache(maxsize=8)
def get_config(settings_path: str = 'config/settings.yaml', env_path: str = '.env') -> AppConfig:
  return SettingsLoader(settings_path=settings_path, env_path=env_path).load()


def clear_config_cache() -> None:
  get_config.cache_clear()


def get_profile_text(profile_path: str = 'config/profile.md') -> str:
  return ProfileLoader(profile_path=profile_path).load()
