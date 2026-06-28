from pathlib import Path

from src.settings import ProfileLoader, SettingsLoader


def test_settings_and_profile_load_from_real_files(tmp_path: Path) -> None:
  config_dir = tmp_path / 'config'
  config_dir.mkdir(parents=True, exist_ok=True)

  settings_path = config_dir / 'settings.yaml'
  settings_path.write_text(
    """
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
  idiomas_permitidos: ["ES", "EN"]
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
""".strip(),
    encoding='utf-8',
  )

  env_path = tmp_path / '.env'
  env_path.write_text('TELEGRAM_TOKEN=test-token\nTELEGRAM_CHAT_ID=12345\n', encoding='utf-8')

  profile_path = config_dir / 'profile.md'
  profile_path.write_text('# Perfil\n\nBackend Python + FastAPI.', encoding='utf-8')

  config = SettingsLoader(str(settings_path), str(env_path)).load()
  profile_text = ProfileLoader(str(profile_path)).load()

  assert config.modelos.juez == 'deepseek-r1:14b'
  assert config.notificacion.telegram_chat_id == '12345'
  assert 'Backend Python' in profile_text

