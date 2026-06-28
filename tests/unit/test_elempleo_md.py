import re

from src.collectors.elempleo import ElempleoCollector, ElempleoParser


def test_html_to_markdown_removes_navigation_and_scripts() -> None:
  html = """
  <html><body>
    <header>Menu principal</header>
    <nav>Links</nav>
    <script>console.log("x")</script>
    <h1>Oferta Backend</h1>
    <p>Experiencia en Python y SQL.</p>
    <footer>Pie</footer>
  </body></html>
  """

  markdown = ElempleoParser.html_to_markdown(html)

  assert 'Oferta Backend' in markdown
  assert 'Experiencia en Python y SQL.' in markdown
  assert 'Menu principal' not in markdown
  assert 'console.log' not in markdown
  assert 'Pie' not in markdown
  assert re.search(r'<[a-zA-Z][^>]*>', markdown) is None


def test_error_result_has_explicit_extraction_status() -> None:
  result = ElempleoCollector._build_error_result(
    url='https://www.elempleo.com/co/ofertas-trabajo/dev/1',
    extraction_status='fetch_failed',
    error='timeout',
  )

  assert result['fuente'] == 'elempleo'
  assert result['extraction_status'] == 'fetch_failed'
  assert result['descripcion_md'] == 'No disponible por error de extraccion.'
  assert result['error'] == 'timeout'

