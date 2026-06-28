from src.collectors.computrabajo import (
  ComputrabajoCollector,
  ComputrabajoParser,
  build_computrabajo_search_url,
  normalize_computrabajo_url,
)


# ---------------------------------------------------------------------------
# normalize_computrabajo_url
# ---------------------------------------------------------------------------

def test_normalize_strips_query_and_fragment() -> None:
  raw = 'https://co.computrabajo.com/oferta/python-dev-XYZABC?refId=foo#top'
  assert normalize_computrabajo_url(raw) == 'https://co.computrabajo.com/oferta/python-dev-XYZABC'


def test_normalize_resolves_relative() -> None:
  assert normalize_computrabajo_url('/oferta/dev-123') == 'https://co.computrabajo.com/oferta/dev-123'


# ---------------------------------------------------------------------------
# build_computrabajo_search_url
# ---------------------------------------------------------------------------

def test_build_url_full_params() -> None:
  url = build_computrabajo_search_url({
    'cargo': 'python developer',
    'jornada': 'tiempo-completo',
    'lugar_trabajo': 'remoto',
    'tipo_contrato': 'indefinido',
    'salario_minimo': 'mas-3m',
    'fecha_publicacion': 'semana',
  })
  assert url.startswith('https://co.computrabajo.com/empleos-de-python-developer')
  assert 'jornada-tiempo-completo' in url
  assert 'en-remoto' in url
  assert 'cont=5' in url    # indefinido
  assert 'sal=7' in url     # mas-3m
  assert 'pubdate=7' in url  # semana


def test_build_url_cargo_only() -> None:
  url = build_computrabajo_search_url({'cargo': 'desarrollador backend'})
  assert url == 'https://co.computrabajo.com/empleos-de-desarrollador-backend'
  assert '?' not in url


def test_build_url_jornada_without_lugar() -> None:
  url = build_computrabajo_search_url({'cargo': 'analista', 'jornada': 'tiempo-completo'})
  assert 'jornada-tiempo-completo' in url
  assert 'en-' not in url


def test_build_url_lugar_without_jornada() -> None:
  url = build_computrabajo_search_url({'cargo': 'diseñador', 'lugar_trabajo': 'bogota'})
  assert 'en-bogota-dc' in url
  assert 'jornada' not in url


def test_build_url_slugifies_cargo_with_accents() -> None:
  url = build_computrabajo_search_url({'cargo': 'Desarrollador Sénior'})
  assert 'empleos-de-desarrollador-senior' in url


def test_build_url_pubdate_hoy() -> None:
  url = build_computrabajo_search_url({'cargo': 'qa', 'fecha_publicacion': 'hoy'})
  assert 'pubdate=1' in url


def test_build_url_pubdate_3dias() -> None:
  url = build_computrabajo_search_url({'cargo': 'qa', 'fecha_publicacion': '3dias'})
  assert 'pubdate=3' in url


def test_build_url_pubdate_mes() -> None:
  url = build_computrabajo_search_url({'cargo': 'qa', 'fecha_publicacion': 'mes'})
  assert 'pubdate=30' in url


def test_build_url_cont_codes() -> None:
  mapping = {
    'ocasional': 1, 'aprendizaje': 2, 'prestacion-servicios': 3,
    'obra-labor': 4, 'indefinido': 5, 'fijo': 6,
  }
  for key, code in mapping.items():
    url = build_computrabajo_search_url({'cargo': 'dev', 'tipo_contrato': key})
    assert f'cont={code}' in url, f'Expected cont={code} for {key}'


def test_build_url_sal_codes() -> None:
  mapping = {
    'menos-700k': 1, 'mas-700k': 2, 'mas-1m': 3, 'mas-1-5m': 4,
    'mas-2m': 5, 'mas-2-5m': 6, 'mas-3m': 7, 'mas-3-5m': 8,
    'mas-4m': 9, 'mas-4-5m': 10, 'mas-5-5m': 11,
  }
  for key, code in mapping.items():
    url = build_computrabajo_search_url({'cargo': 'dev', 'salario_minimo': key})
    assert f'sal={code}' in url, f'Expected sal={code} for {key}'


# ---------------------------------------------------------------------------
# ComputrabajoParser.extract_offer_links
# ---------------------------------------------------------------------------

# Fixture basado en el DOM real de co.computrabajo.com (grid #offersGridOfferContainer)
SAMPLE_LISTING_HTML_ARTICLES = """
<html><body>
  <div id="offersGridOfferContainer" class="box_grid parrilla_oferta">
    <article class="box_offer" data-id="HASH111" id="HASH111">
      <h2 class="fs18 fwB prB">
        <a class="js-o-link fc_base"
           href="/ofertas-de-trabajo/oferta-de-trabajo-de-python-developer-en-bogota-dc-HASH111#lc=Score-0">
          Python Developer
        </a>
      </h2>
    </article>
    <article class="box_offer" data-id="HASH222" id="HASH222">
      <h2 class="fs18 fwB prB">
        <a class="js-o-link fc_base"
           href="/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-en-bogota-dc-HASH222#lc=Score-1">
          Backend Engineer
        </a>
      </h2>
    </article>
    <article class="box_offer" data-id="HASH222" id="HASH222_dup">
      <h2 class="fs18 fwB prB">
        <a class="js-o-link fc_base"
           href="/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-en-bogota-dc-HASH222#lc=Score-2">
          Backend Engineer dup
        </a>
      </h2>
    </article>
    <a href="/empresas/ofertas-de-trabajo-de-acme-XYZ">Not an offer</a>
  </div>
</body></html>
"""

# Fallback: sin grid pero con links directos en el path de oferta
SAMPLE_LISTING_HTML_FALLBACK = """
<html><body>
  <a class="js-o-link"
     href="/ofertas-de-trabajo/oferta-de-trabajo-de-python-developer-en-bogota-dc-HASH111">
    Python Developer
  </a>
  <a class="js-o-link"
     href="/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-HASH222">
    Backend Engineer
  </a>
  <a class="js-o-link"
     href="/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-HASH222#anchor">
    Backend dup
  </a>
  <a href="/empresas/acme-XYZ">Not an offer</a>
</body></html>
"""

OFFER_URL_111 = 'https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-developer-en-bogota-dc-HASH111'
OFFER_URL_222 = 'https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-en-bogota-dc-HASH222'
OFFER_URL_222_FB = 'https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-backend-engineer-HASH222'


def test_parser_extracts_offer_links_via_articles() -> None:
  parser = ComputrabajoParser()
  links = parser.extract_offer_links(SAMPLE_LISTING_HTML_ARTICLES)
  assert OFFER_URL_111 in links
  assert OFFER_URL_222 in links


def test_parser_deduplicates_links_via_articles() -> None:
  parser = ComputrabajoParser()
  links = parser.extract_offer_links(SAMPLE_LISTING_HTML_ARTICLES)
  assert links.count(OFFER_URL_222) == 1


def test_parser_extracts_offer_links_fallback_anchors() -> None:
  """Fallback: links con /ofertas-de-trabajo/oferta-de-trabajo-de- cuando no hay grid."""
  parser = ComputrabajoParser()
  links = parser.extract_offer_links(SAMPLE_LISTING_HTML_FALLBACK)
  assert OFFER_URL_222_FB in links
  assert links.count(OFFER_URL_222_FB) == 1


def test_parser_excludes_non_offer_links() -> None:
  parser = ComputrabajoParser()
  links = parser.extract_offer_links(SAMPLE_LISTING_HTML_ARTICLES)
  assert not any('/empresas/' in link for link in links)


def test_parser_empty_html_returns_empty() -> None:
  parser = ComputrabajoParser()
  assert parser.extract_offer_links('<html><body></body></html>') == []


# ---------------------------------------------------------------------------
# ComputrabajoParser.parse_offer_detail — DOM real 2025
# ---------------------------------------------------------------------------

# Fixture mínimo que replica la estructura real del detalle de oferta
SAMPLE_DETAIL_HTML = """
<html><body>
  <h1>Desarrollador junior</h1>
  <div already-applied-box-container="" description-offer="">
    <div class="mb40 pb40 bb1" div-link="oferta">
      <h3 class="fwB fs18 mb20">Descripción de la oferta</h3>
      <div class="mbB">
        <span class="tag base mb10">$ 4.000.000,00 (Mensual)</span>
        <span class="tag base mb10">Contrato a término indefinido</span>
        <span class="tag base mb10">Tiempo Completo</span>
        <span class="tag base mb10">Remoto</span>
      </div>
      <p class="mbB">Buscamos un desarrollador junior con experiencia en Python y SQL.<br><br>Funciones:<br>1. Levantar requerimientos.<br>2. Diseño de sistemas.</p>
      <p class="fwB fs18 mtB mb10">Requerimientos</p>
      <ul class="disc mbB">
        <li class="mb10">Educación mínima: Universidad / Carrera técnica</li>
        <li class="mb10">1 año de experiencia</li>
        <li class="mb10">Conocimientos: Python, SQL, Java</li>
      </ul>
      <p class="fc_aux fs13 mbB mtB">Palabras clave: developer, programador, jr, junior</p>
      <p class="fc_aux fs13">Ayer (actualizada)</p>
    </div>
    <div class="mb40 pb40 bb1" div-link="empresa">
      <p class="fs18 mb20 fwB">Acerca de&nbsp;TECH CORP S.A.S.</p>
    </div>
  </div>
</body></html>
"""


def test_parse_offer_detail_titulo() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  assert result['titulo'] == 'Desarrollador junior'


def test_parse_offer_detail_empresa_strips_prefix() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  assert result['empresa'] == 'TECH CORP S.A.S.'
  assert 'Acerca de' not in (result['empresa'] or '')


def test_parse_offer_detail_descripcion_contains_metadata_tags() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  md_text = result['descripcion_md'] or ''
  assert '4.000.000' in md_text
  assert 'indefinido' in md_text.lower()
  assert 'Remoto' in md_text or 'remoto' in md_text.lower()


def test_parse_offer_detail_descripcion_contains_main_text() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  md_text = result['descripcion_md'] or ''
  assert 'desarrollador junior' in md_text.lower()
  assert 'Python' in md_text
  assert 'SQL' in md_text


def test_parse_offer_detail_descripcion_has_requisitos_section() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  md_text = result['descripcion_md'] or ''
  assert '## Requerimientos' in md_text
  assert '- Educación mínima' in md_text
  assert '- 1 año de experiencia' in md_text
  assert '- Conocimientos: Python' in md_text


def test_parse_offer_detail_descripcion_has_keywords() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  md_text = result['descripcion_md'] or ''
  assert 'Palabras clave' in md_text or 'palabras clave' in md_text.lower()


def test_parse_offer_detail_no_raw_html_tags() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail(SAMPLE_DETAIL_HTML)
  md_text = result['descripcion_md'] or ''
  assert '<p>' not in md_text
  assert '<li>' not in md_text
  assert '<span' not in md_text


def test_parse_offer_detail_empty_html_returns_none_fields() -> None:
  parser = ComputrabajoParser()
  result = parser.parse_offer_detail('<html><body></body></html>')
  assert result['titulo'] is None
  assert result['empresa'] is None
  assert result['descripcion_md'] == ''


# ---------------------------------------------------------------------------
# ComputrabajoParser.description_html_to_markdown (fallback)
# ---------------------------------------------------------------------------

def test_parser_markdown_removes_tags() -> None:
  html = '<h2>Requisitos</h2><ul><li>Python</li><li>FastAPI</li></ul>'
  parser = ComputrabajoParser()
  result = parser.description_html_to_markdown(html)
  assert '## Requisitos' in result
  assert 'Python' in result
  assert '<' not in result


def test_parser_markdown_preserves_content() -> None:
  html = '<p>Se busca <strong>backend developer</strong> con experiencia en <em>cloud</em>.</p>'
  parser = ComputrabajoParser()
  result = parser.description_html_to_markdown(html)
  assert 'backend developer' in result
  assert 'cloud' in result
  assert '<p>' not in result


# ---------------------------------------------------------------------------
# ComputrabajoCollector.build_search_urls
# ---------------------------------------------------------------------------

def test_collector_builds_multiple_urls() -> None:
  collector = ComputrabajoCollector()
  urls = collector.build_search_urls([
    {'cargo': 'python developer', 'lugar_trabajo': 'remoto', 'tipo_contrato': 'indefinido'},
    {'cargo': 'qa engineer', 'fecha_publicacion': 'hoy'},
  ])
  assert len(urls) == 2
  assert 'empleos-de-python-developer' in urls[0]
  assert 'cont=5' in urls[0]
  assert 'empleos-de-qa-engineer' in urls[1]
  assert 'pubdate=1' in urls[1]


def test_collector_empty_input_returns_empty_list() -> None:
  collector = ComputrabajoCollector()
  assert collector.build_search_urls([]) == []


# ---------------------------------------------------------------------------
# ComputrabajoCollector._fetch_offer — presencia de posted_date
# ---------------------------------------------------------------------------

def test_fetch_offer_result_has_posted_date_key() -> None:
  """El dict de retorno de _fetch_offer() debe incluir posted_date (fecha proxy de scraping)."""
  from datetime import date
  from unittest.mock import AsyncMock, MagicMock, patch

  parser_result = {
    'titulo': 'Backend Dev',
    'empresa': 'ACME',
    'ubicacion': 'Bogotá',
    'descripcion_md': '## Requisitos\n\n- Python',
  }

  collector = ComputrabajoCollector()

  mock_page = AsyncMock()
  mock_response = MagicMock()
  mock_response.status = 200
  mock_page.goto = AsyncMock(return_value=mock_response)
  mock_page.wait_for_selector = AsyncMock(return_value=None)
  mock_page.content = AsyncMock(return_value='<html></html>')

  with patch.object(collector.parser, 'parse_offer_detail', return_value=parser_result):
    import asyncio
    result = asyncio.run(collector._fetch_offer(mock_page, 'https://co.computrabajo.com/ofertas-de-trabajo/backend-dev-XYZABC'))

  assert 'posted_date' in result
  from datetime import UTC, datetime
  today_str = datetime.now(UTC).strftime('%Y-%m-%d')
  assert result['posted_date'] == today_str


def test_build_error_result_has_posted_date_key() -> None:
  """El dict de error también debe incluir posted_date para consistencia."""
  from datetime import UTC, datetime

  result = ComputrabajoCollector._build_error_result(
    'https://co.computrabajo.com/ofertas-de-trabajo/some-offer-ABC',
    'blocked',
    'HTTP 429',
  )

  assert 'posted_date' in result
  today_str = datetime.now(UTC).strftime('%Y-%m-%d')
  assert result['posted_date'] == today_str
