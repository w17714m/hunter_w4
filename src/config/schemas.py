from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


SALARIOS_VALIDOS = {
  '4-45-millones',
  '45-55-millones',
  '55-6-millones',
  '6-8-millones',
  '8-10-millones',
  '10-125-millones',
  '125-15-millones',
  '15-175-millones',
  '175-21-millones',
  'mas-21-millones',
  'salario-confidencial',
}

MODALIDADES_VALIDAS = {'remoto', 'hibrido', 'presencial'}

CONTRACT_TYPES_VALIDOS = {'indefinido', 'fijo', 'obra-labor', 'prestacion-servicios'}

PUBLISH_DATE_VALIDOS = {'hoy', 'semana', 'mes'}


class ElempleoBusqueda(BaseModel):
  url_directa: str | None = None
  cargo: str | None = None
  modalidad: str | None = None
  salarios: list[str] = Field(default_factory=list)
  tipos_contrato: list[str] = Field(default_factory=list)
  fecha_publicacion: str | None = None

  @model_validator(mode='after')
  def validate_tiene_url_o_cargo(self) -> 'ElempleoBusqueda':
    if not self.url_directa and not self.cargo:
      raise ValueError('ElempleoBusqueda requiere url_directa o cargo')
    return self

  @field_validator('modalidad')
  @classmethod
  def validate_modalidad(cls, v: str | None) -> str | None:
    if v is not None and v not in MODALIDADES_VALIDAS:
      raise ValueError(f'modalidad debe ser una de: {MODALIDADES_VALIDAS}')
    return v

  @field_validator('salarios')
  @classmethod
  def validate_salarios(cls, v: list[str]) -> list[str]:
    invalidos = [s for s in v if s not in SALARIOS_VALIDOS]
    if invalidos:
      raise ValueError(f'salarios invalidos: {invalidos}. Validos: {SALARIOS_VALIDOS}')
    return v

  @field_validator('tipos_contrato')
  @classmethod
  def validate_tipos_contrato(cls, v: list[str]) -> list[str]:
    invalidos = [t for t in v if t not in CONTRACT_TYPES_VALIDOS]
    if invalidos:
      raise ValueError(f'tipos_contrato invalidos: {invalidos}. Validos: {CONTRACT_TYPES_VALIDOS}')
    return v

  @field_validator('fecha_publicacion')
  @classmethod
  def validate_fecha_publicacion(cls, v: str | None) -> str | None:
    if v is not None and v not in PUBLISH_DATE_VALIDOS:
      raise ValueError(f'fecha_publicacion debe ser una de: {PUBLISH_DATE_VALIDOS}')
    return v


# Mapping f_WT: work modality
LINKEDIN_MODALIDAD_MAP = {
  'presencial': '1',
  'remoto': '2',
  'hibrido': '3',
}

# Mapping f_TPR: time since publication (in seconds, with 'r' prefix)
LINKEDIN_TIEMPO_PUBLICADO_MAP = {
  '1h': 'r3600',
  '4h': 'r14400',
  '24h': 'r86400',
  'semana': 'r604800',
  'mes': 'r2592000',
}

# Mapping f_JT: contract type
LINKEDIN_TIPO_CONTRATO_MAP = {
  'tiempo-completo': 'F',
  'medio-tiempo': 'P',
  'contrato': 'C',
  'temporal': 'T',
  'pasantia': 'I',
}

LINKEDIN_SORT_MAP = {
  'relevancia': 'R',
  'reciente': 'DD',
}


class LinkedinBusqueda(BaseModel):
  cargo: str
  ubicacion: str | None = None
  geo_id: str | None = None
  modalidades: list[str] = Field(default_factory=list)
  tiempo_publicado: str | None = None
  tipos_contrato: list[str] = Field(default_factory=list)
  easy_apply: bool = False
  orden: str = 'relevancia'

  @model_validator(mode='after')
  def validate_tiene_ubicacion_o_geo_id(self) -> 'LinkedinBusqueda':
    if not self.ubicacion and not self.geo_id:
      raise ValueError('LinkedinBusqueda requiere ubicacion o geo_id')
    return self

  @field_validator('modalidades')
  @classmethod
  def validate_modalidades(cls, v: list[str]) -> list[str]:
    invalidas = [m for m in v if m not in LINKEDIN_MODALIDAD_MAP]
    if invalidas:
      raise ValueError(f'invalid modalidades: {invalidas}. Valid: {list(LINKEDIN_MODALIDAD_MAP)}')
    return v

  @field_validator('tiempo_publicado')
  @classmethod
  def validate_tiempo_publicado(cls, v: str | None) -> str | None:
    if v is not None and v not in LINKEDIN_TIEMPO_PUBLICADO_MAP:
      raise ValueError(f'tiempo_publicado debe ser uno de: {list(LINKEDIN_TIEMPO_PUBLICADO_MAP)}')
    return v

  @field_validator('tipos_contrato')
  @classmethod
  def validate_tipos_contrato(cls, v: list[str]) -> list[str]:
    invalidos = [t for t in v if t not in LINKEDIN_TIPO_CONTRATO_MAP]
    if invalidos:
      raise ValueError(f'invalid tipos_contrato: {invalidos}. Valid: {list(LINKEDIN_TIPO_CONTRATO_MAP)}')
    return v

  @field_validator('orden')
  @classmethod
  def validate_orden(cls, v: str) -> str:
    if v not in LINKEDIN_SORT_MAP:
      raise ValueError(f'orden debe ser uno de: {list(LINKEDIN_SORT_MAP)}')
    return v


# ---------------------------------------------------------------------------
# Computrabajo Colombia — numeric filter maps and path slugs
# ---------------------------------------------------------------------------

# cont= (contract type)
COMPUTRABAJO_CONT_MAP: dict[str, int] = {
  'ocasional': 1,
  'aprendizaje': 2,
  'prestacion-servicios': 3,
  'obra-labor': 4,
  'indefinido': 5,
  'fijo': 6,
}

# sal= (minimum monthly salary in COP)
COMPUTRABAJO_SAL_MAP: dict[str, int] = {
  'menos-700k': 1,
  'mas-700k': 2,
  'mas-1m': 3,
  'mas-1-5m': 4,
  'mas-2m': 5,
  'mas-2-5m': 6,
  'mas-3m': 7,
  'mas-3-5m': 8,
  'mas-4m': 9,
  'mas-4-5m': 10,
  'mas-5-5m': 11,
}

# pubdate= (publication age)
COMPUTRABAJO_PUBDATE_MAP: dict[str, int] = {
  'hoy': 1,
  '3dias': 3,
  'semana': 7,
  'mes': 30,
}

# jornada — path segment (interpolated as "jornada-{slug}")
COMPUTRABAJO_JORNADA_MAP: dict[str, str] = {
  'tiempo-completo': 'tiempo-completo',
  'medio-tiempo': 'medio-tiempo',
  'por-horas': 'por-horas',
  'beca-practicas': 'beca-practicas',
}

# lugar_trabajo — suffix path segment (appended as "en-{slug}")
COMPUTRABAJO_LUGAR_MAP: dict[str, str] = {
  'remoto': 'remoto',
  'bogota': 'bogota-dc',
  'medellin': 'medellin',
  'cali': 'cali',
  'barranquilla': 'barranquilla',
}


class ComputrabajoBusqueda(BaseModel):
  cargo: str
  jornada: str | None = None
  lugar_trabajo: str | None = None
  tipo_contrato: str | None = None
  salario_minimo: str | None = None
  fecha_publicacion: str | None = None

  @field_validator('jornada')
  @classmethod
  def validate_jornada(cls, v: str | None) -> str | None:
    if v is not None and v not in COMPUTRABAJO_JORNADA_MAP:
      raise ValueError(f'jornada debe ser una de: {list(COMPUTRABAJO_JORNADA_MAP)}')
    return v

  @field_validator('lugar_trabajo')
  @classmethod
  def validate_lugar_trabajo(cls, v: str | None) -> str | None:
    if v is not None and v not in COMPUTRABAJO_LUGAR_MAP:
      raise ValueError(f'lugar_trabajo debe ser una de: {list(COMPUTRABAJO_LUGAR_MAP)}')
    return v

  @field_validator('tipo_contrato')
  @classmethod
  def validate_tipo_contrato(cls, v: str | None) -> str | None:
    if v is not None and v not in COMPUTRABAJO_CONT_MAP:
      raise ValueError(f'tipo_contrato debe ser uno de: {list(COMPUTRABAJO_CONT_MAP)}')
    return v

  @field_validator('salario_minimo')
  @classmethod
  def validate_salario_minimo(cls, v: str | None) -> str | None:
    if v is not None and v not in COMPUTRABAJO_SAL_MAP:
      raise ValueError(f'salario_minimo debe ser uno de: {list(COMPUTRABAJO_SAL_MAP)}')
    return v

  @field_validator('fecha_publicacion')
  @classmethod
  def validate_fecha_publicacion(cls, v: str | None) -> str | None:
    if v is not None and v not in COMPUTRABAJO_PUBDATE_MAP:
      raise ValueError(f'fecha_publicacion debe ser uno de: {list(COMPUTRABAJO_PUBDATE_MAP)}')
    return v


class BusquedasConfig(BaseModel):
  elempleo: list[ElempleoBusqueda] = Field(default_factory=list)
  linkedin: list[LinkedinBusqueda] = Field(default_factory=list)
  computrabajo: list[ComputrabajoBusqueda] = Field(default_factory=list)


class SkillsConfig(BaseModel):
  lista: list[str]
  umbral_match: float = Field(ge=0.0, le=1.0)

  @field_validator('lista')
  @classmethod
  def validate_lista(cls, value: list[str]) -> list[str]:
    normalized = [skill.strip() for skill in value if skill.strip()]
    if not normalized:
      raise ValueError('skills.lista no puede estar vacia')
    return normalized


class ModelosConfig(BaseModel):
  ollama_base_url: str
  embeddings: str
  juez: str
  extractor_skills: str = 'qwen3:8b'
  extractor_html: str = 'deepseek-r1:14b'
  extractor_company: str = 'qwen3:8b'


class FiltrosConfig(BaseModel):
  max_days: int = Field(ge=0)
  idiomas_permitidos: list[str]
  umbral_similitud: float = Field(ge=0.0, le=1.0)
  truncar_descripcion_chars: int = Field(gt=0)

  @field_validator('idiomas_permitidos')
  @classmethod
  def validate_idiomas(cls, value: list[str]) -> list[str]:
    normalized = [item.strip().upper() for item in value if item.strip()]
    if not normalized:
      raise ValueError('filtros.idiomas_permitidos no puede estar vacio')
    return normalized


class VectoresConfig(BaseModel):
  path: str
  namespace_perfil: str
  namespace_ofertas: str


class NotificacionConfig(BaseModel):
  telegram_habilitado: bool = True
  telegram_token: str | None = None
  telegram_chat_id: str | None = None

  @model_validator(mode='after')
  def validate_telegram_if_enabled(self) -> 'NotificacionConfig':
    if not self.telegram_habilitado:
      return self
    if not (self.telegram_token or '').strip():
      raise ValueError('TELEGRAM_TOKEN es obligatorio cuando telegram_habilitado=true')
    if not (self.telegram_chat_id or '').strip():
      raise ValueError('TELEGRAM_CHAT_ID es obligatorio cuando telegram_habilitado=true')
    return self


class SalidasConfig(BaseModel):
  markdown_dir: str = 'data/matches'


class BrowserConfig(BaseModel):
  headless: bool = True


class DelaysConfig(BaseModel):
  page_load: tuple[float, float] = (2.0, 5.0)
  between_requests: tuple[float, float] = (0.5, 2.0)
  typing: tuple[float, float] = (0.05, 0.15)


class StealthConfig(BaseModel):
  warp_enabled: bool = False
  warp_cli_path: str = 'warp-cli'  # name only (assumed on PATH); set to absolute path if needed
  max_ip_rotations: int = Field(default=2, ge=0, le=50)
  delays: DelaysConfig = Field(default_factory=DelaysConfig)


class FuentesConfig(BaseModel):
  linkedin_base_url: str = 'https://www.linkedin.com'
  elempleo_base_url: str = 'https://www.elempleo.com'
  computrabajo_base_url: str = 'https://co.computrabajo.com'


class AppConfig(BaseModel):
  busquedas: BusquedasConfig
  skills: SkillsConfig
  modelos: ModelosConfig
  filtros: FiltrosConfig
  vectores: VectoresConfig
  notificacion: NotificacionConfig
  salidas: SalidasConfig
  fuentes: FuentesConfig = Field(default_factory=FuentesConfig)
  browser: BrowserConfig = Field(default_factory=BrowserConfig)
  stealth: StealthConfig = Field(default_factory=StealthConfig)
