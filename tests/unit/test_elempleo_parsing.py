from src.collectors.elempleo import ElempleoCollector, ElempleoParser


def test_elempleo_parser_extracts_unique_offer_links() -> None:
  html = """
  <html><body>
    <a href="/co/ofertas-trabajo/dev-python/111">Oferta 1</a>
    <a href="https://www.elempleo.com/co/ofertas-trabajo/dev-python/111?utm_source=x">Oferta 1 dup</a>
    <a href="/co/ofertas-trabajo/data-engineer/222">Oferta 2</a>
    <a href="/co/empresa/sobre-nosotros">No oferta</a>
  </body></html>
  """
  parser = ElempleoParser()

  links = parser.extract_links(html)

  assert links == [
    'https://www.elempleo.com/co/ofertas-trabajo/dev-python/111',
    'https://www.elempleo.com/co/ofertas-trabajo/data-engineer/222',
  ]


def test_elempleo_parser_extracts_offer_metadata() -> None:
  html = """
  <html>
    <head><meta property="og:site_name" content="ACME" /></head>
    <body>
      <h1>Python Developer</h1>
      <div class="job-location">Bogota</div>
      <time datetime="2026-06-22">22/06/2026</time>
      <section><p>Se requiere experiencia con Python y FastAPI.</p></section>
    </body>
  </html>
  """
  parser = ElempleoParser()

  parsed = parser.parse_offer_page(html, 'https://www.elempleo.com/co/ofertas-trabajo/python-dev/123')

  assert parsed['titulo'] == 'Python Developer'
  assert parsed['empresa'] == 'ACME'
  assert parsed['ubicacion'] == 'Bogota'
  assert parsed['fecha_publicacion'] == '2026-06-22'
  assert 'Python y FastAPI' in parsed['descripcion_md']


def test_elempleo_collector_builds_search_urls() -> None:
  collector = ElempleoCollector()
  urls = collector.build_search_urls(
    [
      {
        'cargo': 'desarrollador python',
        'modalidad': 'remoto',
        'salarios': ['6-8-millones', '8-10-millones'],
        'tipos_contrato': ['indefinido'],
        'fecha_publicacion': 'hoy',
      },
      {
        'cargo': 'backend',
        'salarios': ['mas-21-millones'],
      },
      {
        'url_directa': 'https://www.elempleo.com/co/ofertas-empleo/trabajo-data-engineer',
      },
    ],
  )

  assert urls == [
    'https://www.elempleo.com/co/ofertas-empleo/trabajo-desarrollador-python-modalidad-remoto'
    '?Salaries=6-8-millones:8-10-millones&ContractTypes=indefinido&PublishDate=hoy',
    'https://www.elempleo.com/co/ofertas-empleo/trabajo-backend?Salaries=mas-21-millones',
    'https://www.elempleo.com/co/ofertas-empleo/trabajo-data-engineer',
  ]

