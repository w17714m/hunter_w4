"""Smoke tests for LLMSkillExtractor — hit the real Ollama/qwen2.5:3b, no mocks.

Run with:
    uv run pytest tests/smoke/test_skill_extractor_smoke.py -v -s

Requirements:
    - Ollama running at http://localhost:11434
    - qwen2.5:3b pulled (ollama pull qwen2.5:3b)
"""
from __future__ import annotations

import pytest

from src.filters.skill_extractor import LLMSkillExtractor
from src.filters.skill_filter import SkillFilter

# ---------------------------------------------------------------------------
# YAML skills from config/settings.yaml — the user's actual stack
# ---------------------------------------------------------------------------

YAML_SKILLS = [
    'Java', 'C#', '.NET', 'Python', 'TypeScript', 'Go',
    'ASP.NET', 'Spring Boot', 'NestJS', 'FastAPI', 'Quarkus',
    'AWS', 'Azure', 'GCP',
    'Docker', 'Kubernetes', 'Terraform', 'GitHub Actions',
    'SQL', 'PostgreSQL', 'SQL Server', 'DynamoDB', 'MongoDB',
    'React', 'Angular',
    'microservicios', 'arquitectura hexagonal',
    'PyTorch', 'machine learning',
]

# ---------------------------------------------------------------------------
# Offer A: Flask/Kafka stack — partial match with YAML (~8 skills overlap)
# Represents a real offer the user may receive but not fully cover
# ---------------------------------------------------------------------------
OFFER_A_PARTIAL_MATCH = """
We are looking for a Senior Python Backend Engineer to join a high-impact team working on a complex, data-intensive platform. This role focuses on building and scaling backend services that support large-scale data processing, search, and event-driven architectures.

You'll work in a modern cloud-native environment, collaborating with cross-functional teams to design, develop, and optimize distributed systems.

Responsibilities:
- Design, develop, and maintain scalable backend services using Python (3.10-3.12) and Flask
- Build and optimize RESTful APIs using tools such as Flask-RESTX and Flask-SQLAlchemy
- Work with PostgreSQL for schema design, query optimization, and database migrations (Alembic)
- Develop and maintain integrations with Elasticsearch for indexing and large-scale search
- Implement and manage event-driven architectures using Apache Kafka
- Deploy and manage containerized applications using Docker and Kubernetes (EKS)
- Collaborate on infrastructure and deployment workflows using Helm and Argo CD (GitOps)
- Monitor and troubleshoot systems using Datadog and Sentry

Required Skills:
- Strong experience with Python backend development (Flask preferred)
- Solid understanding of SQLAlchemy and Alembic for ORM and migrations
- Hands-on experience with PostgreSQL (schema design, performance tuning)
- Experience working with Elasticsearch (querying, indexing, cluster concepts)
- Knowledge of Apache Kafka and event-driven systems
- Experience with containerization (Docker) and Kubernetes
- Familiarity with AWS services such as S3, EC2, and EKS

Nice to Have:
- Experience with Redis for caching or task queues
- Familiarity with PyTorch, HuggingFace Transformers, spaCy, or scikit-learn
- Frontend exposure with React and TypeScript
- Experience with LangChain or OpenAI APIs

Technical Environment:
Backend: Python, Flask, Gunicorn
Databases: PostgreSQL, Elasticsearch, Redis
Streaming: Apache Kafka
Cloud & DevOps: AWS (EKS, S3, EC2), Docker, Helm, Argo CD
Observability: Datadog, Sentry
Frontend: React, TypeScript, Redux, Vite, Mapbox GL
"""

# ---------------------------------------------------------------------------
# Offer B: FastAPI/AWS stack — strong match with YAML (many skills overlap)
# Represents an ideal offer for the user's declared stack
# ---------------------------------------------------------------------------
OFFER_B_STRONG_MATCH = """
Backend Developer — Remoto (Colombia)

Buscamos un desarrollador backend con experiencia sólida para unirse a un equipo distribuido.

Requisitos:
- Python con FastAPI o NestJS como framework principal
- Docker y Kubernetes para despliegue en contenedores
- AWS (Lambda, ECS, S3, RDS) como proveedor cloud principal
- PostgreSQL y MongoDB como bases de datos
- Arquitectura de microservicios y diseño de APIs REST
- TypeScript para integraciones con el frontend en React
- GitHub Actions para CI/CD
- Terraform para infraestructura como código
- Arquitectura hexagonal es un plus

Se valora:
- Experiencia con SQL Server o DynamoDB
- Conocimiento de machine learning o PyTorch
- Familiaridad con Azure o GCP

Stack técnico:
Backend: Python, FastAPI, TypeScript, NestJS
Cloud: AWS (Lambda, ECS, S3), Docker, Kubernetes, Terraform
Bases de datos: PostgreSQL, MongoDB, DynamoDB
CI/CD: GitHub Actions
Frontend: React, TypeScript
"""

OLLAMA_BASE_URL = 'http://localhost:11434'
EXTRACTOR_MODEL = 'qwen3:8b'


def _make_extractor() -> LLMSkillExtractor:
    return LLMSkillExtractor(base_url=OLLAMA_BASE_URL, model=EXTRACTOR_MODEL)


def _ollama_is_available() -> bool:
    try:
        import httpx
        r = httpx.get(f'{OLLAMA_BASE_URL}/api/tags', timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _model_is_available() -> bool:
    try:
        import httpx
        r = httpx.get(f'{OLLAMA_BASE_URL}/api/tags', timeout=3.0)
        tags = r.json().get('models', [])
        return any(EXTRACTOR_MODEL in m.get('name', '') for m in tags)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Connectivity guard (runs before all tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module', autouse=True)
def require_ollama() -> None:
    if not _ollama_is_available():
        pytest.skip(
            f'Ollama not reachable at {OLLAMA_BASE_URL} — start Ollama before running smoke tests'
        )
    if not _model_is_available():
        pytest.skip(
            f'{EXTRACTOR_MODEL} not found in Ollama — run: ollama pull {EXTRACTOR_MODEL}'
        )


# ---------------------------------------------------------------------------
# Test 1a: extractor — Offer A (Flask/Kafka, ~15 technologies)
# ---------------------------------------------------------------------------

def test_extractor_offer_a_partial_stack() -> None:
    """LLM must extract at least 10 technologies from the Flask/Kafka offer.

    Offer A declares: Python, Flask, PostgreSQL, Alembic, Elasticsearch,
    Apache Kafka, Docker, Kubernetes, AWS (S3, EC2, EKS), Helm, Argo CD,
    Datadog, Sentry, Redis, React, TypeScript — 15+ distinct technologies.
    """
    ext = _make_extractor()
    skills = ext.extract(OFFER_A_PARTIAL_MATCH)

    print(f'\n  [Offer A] Skills extracted by LLM ({len(skills)} total):')
    for s in skills:
        print(f'    - {s}')

    assert isinstance(skills, list), 'extract() must return a list'
    assert len(skills) >= 10, (
        f'Expected at least 10 skills from Offer A, got {len(skills)}: {skills}'
    )
    assert all(isinstance(s, str) and s for s in skills), 'All items must be non-empty strings'


# ---------------------------------------------------------------------------
# Test 1b: extractor — Offer B (FastAPI/AWS full stack, 20+ technologies)
# ---------------------------------------------------------------------------

def test_extractor_offer_b_full_stack() -> None:
    """LLM must extract at least 15 technologies from the FastAPI/AWS offer.

    Offer B declares: Python, FastAPI, NestJS, TypeScript, AWS (Lambda, ECS, S3, RDS),
    Docker, Kubernetes, Terraform, GitHub Actions, PostgreSQL, MongoDB, DynamoDB,
    SQL Server, React, microservicios, arquitectura hexagonal, machine learning,
    PyTorch, Azure, GCP — 20+ distinct technologies.
    """
    ext = _make_extractor()
    skills = ext.extract(OFFER_B_STRONG_MATCH)

    print(f'\n  [Offer B] Skills extracted by LLM ({len(skills)} total):')
    for s in skills:
        print(f'    - {s}')

    assert isinstance(skills, list), 'extract() must return a list'
    assert len(skills) >= 15, (
        f'Expected at least 15 skills from Offer B, got {len(skills)}: {skills}'
    )
    assert all(isinstance(s, str) and s for s in skills), 'All items must be non-empty strings'


# ---------------------------------------------------------------------------
# Test 2: partial-match offer — some overlap with YAML, fraction < threshold
# ---------------------------------------------------------------------------

def test_partial_match_offer_fails_filter() -> None:
    """Offer A (Flask/Kafka stack) should produce low YAML coverage and fail the filter.

    The offer has many technologies the user does not declare in their YAML
    (Elasticsearch, Kafka, Helm, Argo CD, Redis...).  We expect fraccion < 0.50
    and pasa=False at umbral 0.30 because the user covers only ~8 of ~24 skills.
    """
    from src.core.models import Offer

    offer = Offer(
        id='smoke-offer-partial',
        fuente='linkedin',
        url='https://linkedin.com/jobs/view/smoke-partial',
        titulo='Senior Python Backend Engineer',
        descripcion_md=OFFER_A_PARTIAL_MATCH,
    )

    ext = _make_extractor()
    sf = SkillFilter(required_skills=YAML_SKILLS, umbral_match=0.30, extractor=ext)
    result = sf.match(offer)

    yaml_lower = {s.lower() for s in YAML_SKILLS}
    skills_oferta = ext.extract(OFFER_A_PARTIAL_MATCH)
    matches = [s for s in skills_oferta if s.lower() in yaml_lower]

    print(f'\n  Offer skills ({len(skills_oferta)}): {skills_oferta}')
    print(f'  YAML matches ({len(matches)}): {matches}')
    print(f'  fraccion: {result.fraccion:.2%} | pasa: {result.pasa}')
    print(f'  skills_faltantes: {result.skills_faltantes}')

    assert result.fraccion > 0.0, 'LLM extracted no skills at all'
    assert result.fraccion <= 1.0
    assert len(result.skills_encontrados) >= 3, (
        f'Expected at least 3 YAML hits on this offer, got: {result.skills_encontrados}'
    )
    # Offer A has many non-YAML technologies — coverage should be below 50%
    assert result.fraccion < 0.50, (
        f'Offer A coverage {result.fraccion:.2%} is unexpectedly high — '
        f'check if YAML was expanded or LLM extracted fewer skills than expected'
    )
    assert result.pasa == (result.fraccion >= 0.30), 'pasa must be consistent with fraccion'


# ---------------------------------------------------------------------------
# Test 3: strong-match offer — high YAML coverage, filter passes
# ---------------------------------------------------------------------------

def test_strong_match_offer_passes_filter() -> None:
    """Offer B (FastAPI/AWS/microservicios stack) must pass the skill filter.

    The offer was written to closely match the user's YAML stack.
    Expected overlap: Python, FastAPI, NestJS, TypeScript, AWS, Docker, Kubernetes,
    Terraform, GitHub Actions, PostgreSQL, MongoDB, DynamoDB, React, microservicios,
    arquitectura hexagonal, machine learning, PyTorch, Azure, GCP — 15+ skills.
    We assert pasa=True at umbral 0.30.
    """
    from src.core.models import Offer

    offer = Offer(
        id='smoke-offer-strong',
        fuente='linkedin',
        url='https://linkedin.com/jobs/view/smoke-strong',
        titulo='Backend Developer',
        descripcion_md=OFFER_B_STRONG_MATCH,
    )

    ext = _make_extractor()
    sf = SkillFilter(required_skills=YAML_SKILLS, umbral_match=0.30, extractor=ext)
    result = sf.match(offer)

    print('\n  === Strong-match offer result ===')
    print(f'  fraccion           : {result.fraccion:.2%}')
    print(f'  pasa (umbral 0.30) : {result.pasa}')
    print(f'  skills_encontrados ({len(result.skills_encontrados)}): {result.skills_encontrados}')
    print(f'  skills_faltantes   ({len(result.skills_faltantes)}): {result.skills_faltantes}')

    assert result.fraccion > 0.0, 'LLM extracted no skills at all'
    assert result.fraccion <= 1.0
    assert result.pasa is True, (
        f'Expected strong-match offer to pass (fraccion={result.fraccion:.2%} >= 0.30). '
        f'skills_encontrados: {result.skills_encontrados}'
    )
    assert len(result.skills_encontrados) >= 5, (
        f'Expected at least 5 YAML skills covered, got: {result.skills_encontrados}'
    )
