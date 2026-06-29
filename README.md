# Job Hunter w4

Pipeline de scraping y filtrado de ofertas de empleo desde portales de empleo colombianos y una red profesional global. Extrae descripciones con Playwright, filtra por fecha, idioma y skills, evalúa similitud con tu perfil vía embeddings y LLM, y notifica por Telegram exportando a Markdown.

---

> ## Aviso legal / Disclaimer
>
> **Este proyecto fue creado exclusivamente con fines educativos y de aprendizaje personal.**
>
> El autor no se hace responsable de ningún daño directo, indirecto, incidental o consecuente derivado del uso o mal uso de este software. El uso de este proyecto es bajo la entera responsabilidad del usuario.
>
> En particular:
>
> - **Términos de servicio**: El uso de este software puede violar los Términos de Servicio de las plataformas de empleo con las que interactúa. El autor no apoya ni fomenta dicha violación.
> - **Bloqueos de cuenta**: El autor no es responsable de bloqueos temporales o permanentes de cuentas derivados del uso de este software.
> - **Uso indebido**: No utilices este software para recolección masiva de datos, acoso, spam u otros fines maliciosos.
> - **Sin garantía**: El software se distribuye "tal cual" (*AS IS*), sin garantías de ningún tipo, ya sean expresas o implícitas.
>
> Consulta el archivo [LICENSE](LICENSE) para los términos completos de la licencia MIT.

---

## Tabla de contenidos

- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración](#configuración)
  - [Variables de entorno (.env)](#1-variables-de-entorno--env)
  - [Perfil profesional (profile.md)](#2-perfil-profesional--configprofilemd)
  - [Archivo principal (settings.yaml)](#3-archivo-principal--configsettingsyaml)
    - [busquedas.elempleo](#busquedaselempleo)
    - [busquedas.computrabajo](#busquedascomputrabajo)
    - [busquedas.linkedin](#busquedaslinkedin)
    - [skills](#skills)
    - [modelos](#modelos)
    - [filtros](#filtros)
    - [vectores](#vectores)
    - [notificacion](#notificacion)
    - [salidas](#salidas)
    - [browser](#browser)
    - [stealth](#stealth)
- [Sesión autenticada](#sesión-autenticada)
- [Verificar entorno](#verificar-entorno)
- [Ejecutar el pipeline](#ejecutar-el-pipeline)
- [Qué hace cada ciclo](#qué-hace-cada-ciclo)
- [Salidas](#salidas-1)
- [Tests](#tests)

---

## Requisitos previos

| Herramienta | Versión mínima | Notas |
|---|---|---|
| Python | 3.12 | |
| [uv](https://docs.astral.sh/uv/) | cualquiera | gestor de paquetes y entornos virtuales |
| [Ollama](https://ollama.ai) | cualquiera | debe estar corriendo en `localhost:11434` |
| [Cloudflare WARP](https://1.1.1.1/) | cualquiera | opcional — rotación de IP para evitar bloqueos |
| Chromium (Playwright) | — | se instala con el comando de abajo |

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd Hunter_w4

# 2. Instalar dependencias Python
uv sync

# 3. Instalar Chromium para Playwright
uv run playwright install chromium

# 4. Descargar modelos de Ollama
ollama pull nomic-embed-text
ollama pull deepseek-r1:14b   # juez LLM — puede sustituirse por cualquier modelo de Ollama
ollama pull qwen3:8b          # extractor de skills — puede sustituirse

# 5. Crear archivos de configuración a partir de los ejemplos
cp .env.example .env
cp config/settings.yaml.example config/settings.yaml
cp config/profile.md.example config/profile.md

# 6. Editar cada archivo con tus datos reales
# .env              → token y chat_id de Telegram
# config/settings.yaml → búsquedas, skills, filtros, modelos
# config/profile.md → tu perfil / CV resumido
```

> **Importante**: Los archivos `.env`, `config/settings.yaml` y `config/profile.md` contienen datos personales y credenciales. Están en `.gitignore` y **nunca deben subirse a GitHub**. Los archivos `.example` son plantillas sin datos reales y sí están versionados.

---

## Configuración

### 1. Variables de entorno — `.env`

Crea un archivo `.env` en la raíz del proyecto con las siguientes variables:

```env
TELEGRAM_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxYZ
TELEGRAM_CHAT_ID=-100123456789
```

| Variable | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `TELEGRAM_TOKEN` | `string` | Sí (si Telegram habilitado) | Token del bot de Telegram. Obtenlo con [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | `string` | Sí (si Telegram habilitado) | ID del chat o canal donde se envían las notificaciones. Puede ser negativo para grupos/canales |

Si no usas Telegram, establece `telegram_habilitado: false` en `settings.yaml` y omite estas variables.

---

### 2. Perfil profesional — `config/profile.md`

Escribe aquí tu CV resumido en Markdown. El juez LLM usa este texto como contexto para decidir si una oferta encaja con tu perfil. Entre más específico, mejor funciona.

```markdown
# Perfil

Soy desarrollador backend con 5 años de experiencia en Python (FastAPI, Django).
Stack principal: Python, PostgreSQL, Docker, AWS Lambda, Redis.
Busco roles remotos, modalidad indefinida, salario desde 5M COP.
No me interesan roles de QA ni frontend puro.
Tengo experiencia liderando equipos pequeños (2-4 personas).
```

---

### 3. Archivo principal — `config/settings.yaml`

Este es el archivo central de configuración. Cada sección se describe a continuación con todos sus parámetros, tipos y valores aceptados.

---

#### `busquedas.elempleo`

Lista de búsquedas a ejecutar en el portal de empleo **A** (fuente `elempleo`). Cada elemento es un objeto con los siguientes campos:

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `cargo` | `string` | Sí (o `url_directa`) | Texto de búsqueda, ej: `"desarrollador backend"` |
| `url_directa` | `string` | Sí (o `cargo`) | URL directa de búsqueda del portal. Alternativa a construir la URL por parámetros |
| `modalidad` | `string \| null` | No | Tipo de lugar de trabajo |
| `salarios` | `list[string]` | No | Rangos salariales a incluir. Lista vacía = todos |
| `tipos_contrato` | `list[string]` | No | Tipos de contrato a incluir. Lista vacía = todos |
| `fecha_publicacion` | `string \| null` | No | Antigüedad máxima de la oferta |

**Valores válidos para `modalidad`:**

| Valor | Descripción |
|---|---|
| `"remoto"` | Trabajo 100% remoto |
| `"hibrido"` | Trabajo híbrido |
| `"presencial"` | Trabajo presencial |

**Valores válidos para `salarios`:**

| Valor | Rango aproximado (COP mensual) |
|---|---|
| `"4-45-millones"` | $4.000.000 – $4.500.000 |
| `"45-55-millones"` | $4.500.000 – $5.500.000 |
| `"55-6-millones"` | $5.500.000 – $6.000.000 |
| `"6-8-millones"` | $6.000.000 – $8.000.000 |
| `"8-10-millones"` | $8.000.000 – $10.000.000 |
| `"10-125-millones"` | $10.000.000 – $12.500.000 |
| `"125-15-millones"` | $12.500.000 – $15.000.000 |
| `"15-175-millones"` | $15.000.000 – $17.500.000 |
| `"175-21-millones"` | $17.500.000 – $21.000.000 |
| `"mas-21-millones"` | Más de $21.000.000 |
| `"salario-confidencial"` | Salario no publicado |

**Valores válidos para `tipos_contrato`:**

| Valor | Descripción |
|---|---|
| `"indefinido"` | Contrato a término indefinido |
| `"fijo"` | Contrato a término fijo |
| `"obra-labor"` | Contrato por obra o labor |
| `"prestacion-servicios"` | Prestación de servicios / freelance |

**Valores válidos para `fecha_publicacion`:**

| Valor | Descripción |
|---|---|
| `"hoy"` | Publicadas hoy |
| `"semana"` | Publicadas en la última semana |
| `"mes"` | Publicadas en el último mes |

**Ejemplo:**

```yaml
busquedas:
  elempleo:
    - cargo: "desarrollador backend"
      modalidad: "remoto"
      salarios:
        - "6-8-millones"
        - "8-10-millones"
        - "mas-21-millones"
        - "salario-confidencial"
      tipos_contrato:
        - "indefinido"
      fecha_publicacion: "hoy"
    - cargo: "ingeniero de software"
      modalidad: "remoto"
      fecha_publicacion: "semana"
```

---

#### `busquedas.computrabajo`

Lista de búsquedas a ejecutar en el portal de empleo **B** (fuente `computrabajo`). Cada elemento:

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `cargo` | `string` | Sí | Texto de búsqueda, ej: `"desarrollador backend"` |
| `jornada` | `string \| null` | No | Tipo de jornada laboral |
| `lugar_trabajo` | `string \| null` | No | Ubicación o modalidad |
| `tipo_contrato` | `string \| null` | No | Tipo de contrato (solo uno, a diferencia del portal A) |
| `salario_minimo` | `string \| null` | No | Salario mínimo mensual |
| `fecha_publicacion` | `string \| null` | No | Antigüedad máxima de la oferta |

**Valores válidos para `jornada`:**

| Valor | Descripción |
|---|---|
| `"tiempo-completo"` | Jornada completa |
| `"medio-tiempo"` | Media jornada |
| `"por-horas"` | Por horas |
| `"beca-practicas"` | Beca o prácticas |

**Valores válidos para `lugar_trabajo`:**

| Valor | Descripción |
|---|---|
| `"remoto"` | Trabajo remoto |
| `"bogota"` | Bogotá D.C. |
| `"medellin"` | Medellín |
| `"cali"` | Cali |
| `"barranquilla"` | Barranquilla |

**Valores válidos para `tipo_contrato`:**

| Valor | Descripción |
|---|---|
| `"indefinido"` | A término indefinido |
| `"fijo"` | A término fijo |
| `"obra-labor"` | Por obra o labor |
| `"prestacion-servicios"` | Prestación de servicios |
| `"ocasional"` | Trabajo ocasional |
| `"aprendizaje"` | Contrato de aprendizaje |

**Valores válidos para `salario_minimo`:**

| Valor | Salario mínimo mensual (COP) |
|---|---|
| `"menos-700k"` | Menos de $700.000 |
| `"mas-700k"` | Más de $700.000 |
| `"mas-1m"` | Más de $1.000.000 |
| `"mas-1-5m"` | Más de $1.500.000 |
| `"mas-2m"` | Más de $2.000.000 |
| `"mas-2-5m"` | Más de $2.500.000 |
| `"mas-3m"` | Más de $3.000.000 |
| `"mas-3-5m"` | Más de $3.500.000 |
| `"mas-4m"` | Más de $4.000.000 |
| `"mas-4-5m"` | Más de $4.500.000 |
| `"mas-5-5m"` | Más de $5.500.000 |

**Valores válidos para `fecha_publicacion`:**

| Valor | Descripción |
|---|---|
| `"hoy"` | Publicadas hoy |
| `"3dias"` | Últimos 3 días |
| `"semana"` | Última semana |
| `"mes"` | Último mes |

**Ejemplo:**

```yaml
busquedas:
  computrabajo:
    - cargo: "desarrollador backend"
      lugar_trabajo: "remoto"
      tipo_contrato: "indefinido"
      salario_minimo: "mas-5-5m"
      fecha_publicacion: "3dias"
    - cargo: "ingeniero de software"
      lugar_trabajo: "bogota"
      jornada: "tiempo-completo"
      fecha_publicacion: "semana"
```

---

#### `busquedas.linkedin`

Lista de búsquedas a ejecutar en la red profesional **C** (fuente `linkedin`). Requiere sesión autenticada (ver [Sesión autenticada](#sesión-autenticada)). Cada elemento:

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `cargo` | `string` | Sí | Texto de búsqueda, ej: `"backend developer"` |
| `geo_id` | `string \| null` | Sí (o `ubicacion`) | ID geográfico del portal. `"100876405"` = Colombia |
| `ubicacion` | `string \| null` | Sí (o `geo_id`) | Nombre de ciudad/país en texto libre, ej: `"Bogotá"` |
| `modalidades` | `list[string]` | No | Modalidades de trabajo. Lista vacía = todas |
| `tiempo_publicado` | `string \| null` | No | Antigüedad máxima de la oferta |
| `tipos_contrato` | `list[string]` | No | Tipos de contrato. Lista vacía = todos |
| `easy_apply` | `bool` | No | `true` = solo ofertas con postulación directa. Default: `false` |
| `orden` | `string` | No | Criterio de ordenamiento. Default: `"relevancia"` |

**Valores válidos para `modalidades`:**

| Valor | Descripción |
|---|---|
| `"presencial"` | En oficina |
| `"remoto"` | Trabajo remoto |
| `"hibrido"` | Modalidad híbrida |

**Valores válidos para `tiempo_publicado`:**

| Valor | Descripción |
|---|---|
| `"1h"` | Última hora |
| `"4h"` | Últimas 4 horas |
| `"24h"` | Últimas 24 horas |
| `"semana"` | Última semana |
| `"mes"` | Último mes |

> **Nota**: El portal C ignora el filtro de tiempo en páginas de resultados profundas (más allá de la página 5-6). El `DateFilter` del pipeline (`filtros.max_days`) descarta las que superen el límite configurado antes de guardarlas.

**Valores válidos para `tipos_contrato`:**

| Valor | Descripción |
|---|---|
| `"tiempo-completo"` | Full time |
| `"medio-tiempo"` | Part time |
| `"contrato"` | Por contrato |
| `"temporal"` | Temporal |
| `"pasantia"` | Pasantía / internship |

**Valores válidos para `orden`:**

| Valor | Descripción |
|---|---|
| `"relevancia"` | Por relevancia (default del portal) |
| `"reciente"` | Por fecha de publicación descendente |

**Ejemplo:**

```yaml
busquedas:
  linkedin:
    - cargo: "backend developer"
      geo_id: "100876405"
      modalidades:
        - "remoto"
      tiempo_publicado: "semana"
      tipos_contrato:
        - "tiempo-completo"
        - "contrato"
      easy_apply: false
      orden: "reciente"
    - cargo: "software engineer"
      geo_id: "100876405"
      modalidades:
        - "remoto"
        - "hibrido"
      tiempo_publicado: "semana"
      orden: "reciente"
```

---

#### `skills`

Define el stack técnico del candidato. Se usa para filtrar ofertas antes de invocar el LLM.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `lista` | `list[string]` | Sí | Skills del candidato. No puede estar vacío |
| `umbral_match` | `float` | Sí | Fracción mínima de skills de la oferta que deben estar en `lista`. Rango: `0.0`–`1.0` |

**Lógica**: el extractor de skills (LLM) identifica las skills requeridas en la descripción de la oferta. Si el porcentaje de esas skills que aparecen en tu `lista` es menor que `umbral_match`, la oferta se descarta sin pasar al juez.

**Ejemplo:**

```yaml
skills:
  lista:
    - Python
    - TypeScript
    - FastAPI
    - NestJS
    - PostgreSQL
    - Docker
    - AWS
    - Kubernetes
  umbral_match: 0.30   # al menos 30% de las skills de la oferta deben estar en tu lista
```

---

#### `modelos`

Configuración de los modelos de Ollama usados en el pipeline.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `ollama_base_url` | `string` | Sí | URL base de la API de Ollama |
| `embeddings` | `string` | Sí | Modelo para generar embeddings del perfil y ofertas |
| `juez` | `string` | Sí | Modelo LLM para evaluar si una oferta encaja con el perfil |
| `extractor_skills` | `string` | No | Modelo LLM para extraer skills de la descripción. Default: `"qwen3:8b"` |

**Ejemplo:**

```yaml
modelos:
  ollama_base_url: "http://localhost:11434"
  embeddings: "nomic-embed-text"
  juez: "deepseek-r1:14b"
  extractor_skills: "qwen3:8b"
```

Puedes sustituir cualquier modelo por otro disponible en tu instalación de Ollama (`ollama list`). El modelo de embeddings debe ser el mismo que se usó al indexar el perfil; si lo cambias, borra `data/lancedb/` y vuelve a correr.

---

#### `filtros`

Umbrales del pipeline de filtrado. Las ofertas que no superen cada filtro son descartadas antes de llegar al siguiente.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `max_days` | `int` | Sí | Máximo de días desde la publicación. `≥ 0`. Ofertas más antiguas se descartan |
| `idiomas_permitidos` | `list[string]` | Sí | Códigos ISO 639-1 en mayúsculas. Al menos uno requerido |
| `umbral_similitud` | `float` | Sí | Similitud coseno mínima entre la oferta y el perfil. Rango: `0.0`–`1.0` |
| `truncar_descripcion_chars` | `int` | Sí | Caracteres máximos de descripción enviados al juez LLM. `> 0` |

**Valores comunes para `idiomas_permitidos`:**

| Valor | Idioma |
|---|---|
| `"ES"` | Español |
| `"EN"` | Inglés |
| `"PT"` | Portugués |

**Ejemplo:**

```yaml
filtros:
  max_days: 2
  idiomas_permitidos:
    - "ES"
  umbral_similitud: 0.65
  truncar_descripcion_chars: 4000
```

---

#### `vectores`

Configuración del vector store (LanceDB) donde se almacenan embeddings del perfil y las ofertas.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `path` | `string` | Sí | Ruta local del directorio de LanceDB. Relativa a la raíz del proyecto |
| `namespace_perfil` | `string` | Sí | Nombre de la tabla para los embeddings del perfil |
| `namespace_ofertas` | `string` | Sí | Nombre de la tabla para los embeddings de las ofertas indexadas |

**Ejemplo:**

```yaml
vectores:
  path: "data/lancedb"
  namespace_perfil: "perfil"
  namespace_ofertas: "ofertas"
```

---

#### `notificacion`

Configuración del bot de Telegram para notificaciones en tiempo real.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `telegram_habilitado` | `bool` | No | Activa/desactiva las notificaciones. Default: `true` |
| `telegram_token` | `string \| null` | Condicional | Token del bot. Tomado de `TELEGRAM_TOKEN` en `.env` si no se especifica aquí |
| `telegram_chat_id` | `string \| null` | Condicional | ID del chat destino. Tomado de `TELEGRAM_CHAT_ID` en `.env` |

> Recomendado: mantener el token y el chat_id en `.env` y no en el YAML para evitar exponerlos accidentalmente.

**Ejemplo:**

```yaml
notificacion:
  telegram_habilitado: true
  # telegram_token y telegram_chat_id se leen del .env
```

---

#### `salidas`

Configuración de exportación de resultados a disco.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `markdown_dir` | `string` | No | Directorio donde se exportan los archivos `.md` de ofertas aprobadas. Default: `"data/matches"` |

**Ejemplo:**

```yaml
salidas:
  markdown_dir: "data/matches"
```

---

#### `browser`

Configuración del navegador Playwright usado para el scraping.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `headless` | `bool` | No | `true` = navegador invisible (recomendado para producción). `false` = muestra la ventana del navegador (útil para depuración). Default: `true` |

**Ejemplo:**

```yaml
browser:
  headless: false   # false para ver el navegador durante el scraping
```

---

#### `stealth`

Configuración anti-detección para el scraping. Incluye rotación de IP con Cloudflare WARP y delays humanizados.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `warp_enabled` | `bool` | No | Activa la rotación de IP vía Cloudflare WARP CLI. Default: `false` |
| `warp_cli_path` | `string` | No | Ruta o nombre del ejecutable `warp-cli`. Default: `"warp-cli"` (asume que está en PATH) |
| `max_ip_rotations` | `int` | No | Máximo de rotaciones de IP por URL bloqueada. Rango: `0`–`50`. Default: `2` |
| `delays` | `objeto` | No | Tiempos de espera aleatorios para simular comportamiento humano |
| `delays.page_load` | `[float, float]` | No | Rango `[min, max]` en segundos de espera tras cargar una página. Default: `[2.0, 5.0]` |
| `delays.between_requests` | `[float, float]` | No | Rango `[min, max]` en segundos entre solicitudes consecutivas. Default: `[0.5, 2.0]` |
| `delays.typing` | `[float, float]` | No | Rango `[min, max]` en segundos entre pulsaciones de teclado simuladas. Default: `[0.05, 0.15]` |

**Ejemplo:**

```yaml
stealth:
  warp_enabled: true
  warp_cli_path: "warp-cli"
  max_ip_rotations: 5
  delays:
    page_load: [2.0, 5.0]
    between_requests: [0.5, 2.0]
    typing: [0.05, 0.15]
```

Para usar WARP: instala [Cloudflare WARP](https://1.1.1.1/) en tu sistema y asegúrate de que `warp-cli` esté en el PATH o especifica la ruta absoluta.

---

## Sesión autenticada

El portal C requiere autenticación. Ejecuta este script **una sola vez** antes de la primera corrida:

```bash
uv run python scripts/login_linkedin_persistent.py
```

Se abre un navegador Chromium: inicia sesión manualmente con tu cuenta. El perfil de sesión queda guardado en `data/playwright/linkedin-profile/` y se reutiliza en todas las corridas siguientes.

Si el portal bloquea la sesión (aparece `authwall` en los logs), vuelve a ejecutar el script.

---

## Verificar entorno

Antes de la primera corrida, verifica que todos los servicios estén disponibles:

```bash
uv run python scripts/setup_check.py
```

Muestra un reporte con estado `ok` / `warn` / `fail` para cada componente: Ollama, modelos, Telegram, Chromium, LanceDB, etc. Sale con código 1 si algún check falla.

---

## Ejecutar el pipeline

### Ciclo único

Ejecuta una sola pasada completa y termina:

```bash
uv run python -m src.runner --once
```

### Ciclo de prueba

Extrae 1 oferta por fuente y la pasa por el pipeline completo con logs detallados. Útil para verificar la configuración sin consumir el budget completo:

```bash
uv run python -m src.runner --trial
```

### Scheduler automático

Ejecuta un ciclo de inmediato y luego repite cada N minutos:

```bash
# Cada 60 minutos (default)
uv run python -m src.runner

# Cada 30 minutos
uv run python -m src.runner --interval 30
```

Detener con `Ctrl+C`.

---

## Qué hace cada ciclo

```
Scraping (portal A + portal B + portal C)
    ↓
Dedup por URL              — omite ofertas ya visitadas en ciclos anteriores (consulta SQLite)
    ↓
Paginación adaptativa      — portal C sigue paginando hasta encontrar 150 URLs nuevas
    ↓
Normalización              — extrae título, empresa, fecha, descripción en Markdown
    ↓
Dedup interna              — descarta si el ID (hash de URL) ya está en la DB
    ↓
Filtro de fecha            — descarta si la oferta supera filtros.max_days días de antigüedad
    ↓
Filtro de idioma           — descarta si el idioma detectado no está en idiomas_permitidos
    ↓
Filtro de skills           — extrae skills con LLM; descarta si no alcanza umbral_match
    ↓
Similitud vectorial        — descarta si similitud coseno con el perfil < umbral_similitud
    ↓
Juez LLM                   — el modelo juez decide si la oferta encaja con tu perfil
    ↓
Notificación Telegram      — envía mensaje con título, empresa, skills, veredicto y URL
Exportación Markdown       — guarda en salidas.markdown_dir/<fuente>_<id>.md
    ↓
Persistencia SQLite        — guarda estado final de cada oferta en data/offers.db
```

Los estados finales posibles en la DB son: `notified`, `low_sim`, `old`, `other_lang`, `low_skills`, `duplicate`, `error_normalizacion`.

---

## Salidas

| Destino | Contenido |
|---|---|
| `data/matches/` | Archivos `.md` por oferta que superó todos los filtros, con descripción completa y veredicto del juez |
| `data/lancedb/` | Vector store LanceDB con embeddings del perfil y ofertas indexadas |
| `data/offers.db` | SQLite con historial de todas las ofertas procesadas, su estado final, similitud, skills y veredicto |
| Telegram | Notificación en tiempo real por cada oferta aprobada, con enlace directo |

---

## Tests

```bash
# Suite rápida — solo unitarios (no requiere servicios externos)
uv run pytest tests/unit/

# Suite completa — incluye tests con Ollama, Playwright y Telegram reales
uv run pytest --run-integration
```
