"""Pruebas de conversión HTML → Markdown para los collectors de elempleo y LinkedIn.

Verifica que la salida:
  - No contiene etiquetas HTML.
  - No contiene contenido de <nav>, <footer>, <script>, <header>.
  - Preserva el texto relevante de la oferta.
  - Contiene los skills buscables en el Markdown resultante.
"""
from __future__ import annotations

import re

from src.collectors.elempleo import ElempleoParser
from src.collectors.linkedin import LinkedInExtractor


# ---------------------------------------------------------------------------
# Fixtures HTML — elempleo (simulando estructura real del DOM 2025)
# ---------------------------------------------------------------------------

ELEMPLEO_HTML_FULL = """
<html>
<head><title>Oferta</title></head>
<body>
  <header>
    <nav>Inicio | Buscar | Login</nav>
  </header>
  <script>window.__PRELOADED_STATE__ = {"user": null};</script>
  <main>
    <h1 class="title-offer">Desarrollador Backend Python</h1>
    <div class="company-info">
      <span class="company-name">TechCorp SAS</span>
      <span class="location">Bogotá, Colombia</span>
    </div>
    <time datetime="2025-06-01">Publicado hace 2 días</time>
    <div class="offer-description">
      <h2>Descripción del cargo</h2>
      <p>Buscamos un desarrollador con experiencia sólida en <strong>Python</strong>,
         <strong>FastAPI</strong> y <strong>Docker</strong>.</p>
      <ul>
        <li>Mínimo 3 años de experiencia en Python</li>
        <li>Conocimiento en AWS y microservicios</li>
        <li>Manejo de bases de datos PostgreSQL</li>
      </ul>
      <h3>Ofrecemos</h3>
      <p>Salario competitivo, trabajo remoto, crecimiento profesional.</p>
    </div>
  </main>
  <footer>
    <p>© 2025 elempleo.com - Todos los derechos reservados</p>
    <nav>Política de privacidad | Términos</nav>
  </footer>
</body>
</html>
"""

ELEMPLEO_HTML_MINIMAL = """
<html><body>
  <div class="offer-description">
    <p>Se requiere Python y SQL para este rol de análisis de datos.</p>
  </div>
</body></html>
"""

ELEMPLEO_HTML_WITH_SCRIPTS = """
<html><body>
  <script>alert('xss');</script>
  <style>.hidden { display: none; }</style>
  <aside>Publicidad: Haz click aquí</aside>
  <div class="offer-description">
    <p>Desarrollador Java con Spring Boot. Experiencia en AWS requerida.</p>
  </div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Fixtures HTML — LinkedIn (simulando el bloque de descripción extraído)
# ---------------------------------------------------------------------------

LINKEDIN_DESC_HTML = """
<div class="jobs-description__content">
  <h2>About the role</h2>
  <p>We are looking for a <strong>Python</strong> backend engineer with expertise in
     <strong>FastAPI</strong>, <strong>Docker</strong>, and cloud technologies.</p>
  <ul>
    <li>3+ years of Python experience</li>
    <li>Experience with REST APIs and microservices</li>
    <li>AWS or GCP cloud deployment</li>
    <li>PostgreSQL or MongoDB database management</li>
  </ul>
  <h3>Nice to have</h3>
  <ul>
    <li>Knowledge of Kubernetes</li>
    <li>Experience with CI/CD pipelines</li>
  </ul>
</div>
"""

LINKEDIN_DESC_HTML_WITH_NOISE = """
<div>
  <script>trackPageView('job-detail');</script>
  <style>body { font-family: Arial; }</style>
  <div class="jobs-description__content">
    <p>Desarrollador <em>Python</em> senior con experiencia en <em>FastAPI</em> y Docker.</p>
    <ul>
      <li>Experiencia con SQL y NoSQL</li>
      <li>Conocimientos en AWS Lambda</li>
    </ul>
  </div>
</div>
"""

LINKEDIN_DESC_HTML_SIMPLE = """
<p>Python developer with FastAPI and PostgreSQL skills needed for a fintech startup.</p>
"""


# ---------------------------------------------------------------------------
# Tests — ElempleoParser.html_to_markdown
# ---------------------------------------------------------------------------

class TestElempleoHtmlToMarkdown:
    def test_output_contains_no_html_tags(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert re.search(r'<[a-zA-Z][^>]*>', result) is None

    def test_removes_nav_content(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert 'Inicio | Buscar | Login' not in result
        assert 'Política de privacidad' not in result

    def test_removes_footer_content(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert 'Todos los derechos reservados' not in result

    def test_removes_header_content(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        # El contenido de <header> debe haberse eliminado
        # "Inicio | Buscar | Login" está en <nav> dentro de <header>
        assert 'Inicio | Buscar | Login' not in result

    def test_removes_script_content(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert '__PRELOADED_STATE__' not in result
        assert 'window.' not in result

    def test_removes_scripts_explicitly(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_WITH_SCRIPTS)
        assert "alert('xss')" not in result
        assert '.hidden' not in result

    def test_removes_aside_content(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_WITH_SCRIPTS)
        assert 'Publicidad' not in result

    def test_preserves_job_description_text(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert 'Buscamos un desarrollador' in result
        assert 'salario competitivo' in result.lower() or 'Salario competitivo' in result

    def test_skills_are_searchable_in_output(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        for skill in ['Python', 'FastAPI', 'Docker', 'AWS', 'PostgreSQL']:
            assert skill in result, f'Skill "{skill}" no encontrado en el Markdown'

    def test_preserves_list_items(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert 'Mínimo 3 años' in result or '3 años' in result

    def test_minimal_html_produces_nonempty_output(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_MINIMAL)
        assert result.strip()
        assert 'Python' in result
        assert 'SQL' in result

    def test_output_is_string(self) -> None:
        result = ElempleoParser.html_to_markdown(ELEMPLEO_HTML_FULL)
        assert isinstance(result, str)

    def test_empty_html_returns_empty_string(self) -> None:
        result = ElempleoParser.html_to_markdown('<html><body></body></html>')
        assert result.strip() == ''


# ---------------------------------------------------------------------------
# Tests — LinkedInExtractor.description_html_to_markdown
# ---------------------------------------------------------------------------

class TestLinkedInHtmlToMarkdown:
    def test_output_contains_no_html_tags(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML)
        assert re.search(r'<[a-zA-Z][^>]*>', result) is None

    def test_preserves_section_headers(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML)
        assert 'About the role' in result or '## About the role' in result

    def test_skills_are_searchable_in_output(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML)
        for skill in ['Python', 'FastAPI', 'Docker', 'AWS']:
            assert skill in result, f'Skill "{skill}" no encontrado en el Markdown'

    def test_list_items_are_preserved(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML)
        assert 'REST APIs' in result or 'microservices' in result

    def test_removes_script_content_from_noisy_html(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML_WITH_NOISE)
        assert 'trackPageView' not in result
        assert 'font-family' not in result

    def test_preserves_description_text_despite_noise(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML_WITH_NOISE)
        assert 'Python' in result
        assert 'FastAPI' in result
        assert 'Docker' in result

    def test_simple_paragraph_converts_correctly(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML_SIMPLE)
        assert 'Python' in result
        assert 'FastAPI' in result
        assert 'PostgreSQL' in result
        assert '<p>' not in result

    def test_output_is_non_empty_string(self) -> None:
        result = LinkedInExtractor().description_html_to_markdown(LINKEDIN_DESC_HTML)
        assert isinstance(result, str)
        assert result.strip()

    def test_bold_emphasis_converted_to_markdown(self) -> None:
        html = '<p><strong>Python</strong> es el lenguaje principal.</p>'
        result = LinkedInExtractor().description_html_to_markdown(html)
        # El skill debe estar presente aunque el bold se convierta o elimine
        assert 'Python' in result
        assert '<strong>' not in result
