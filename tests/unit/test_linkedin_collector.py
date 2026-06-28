from src.collectors.linkedin import LinkedInExtractor, build_linkedin_search_url, normalize_linkedin_url


def test_normalize_linkedin_url_strips_query_and_fragment() -> None:
  raw = 'https://www.linkedin.com/jobs/view/12345?refId=abc&trackingId=xyz#apply'
  assert normalize_linkedin_url(raw) == 'https://www.linkedin.com/jobs/view/12345'


def test_normalize_linkedin_url_resolves_relative() -> None:
  assert normalize_linkedin_url('/jobs/view/99') == 'https://www.linkedin.com/jobs/view/99'


def test_build_linkedin_search_url_with_geo_id_and_filters() -> None:
  url = build_linkedin_search_url({
    'cargo': 'python developer',
    'geo_id': '100876405',
    'modalidades': ['remoto'],
    'tiempo_publicado': '24h',
    'tipos_contrato': ['tiempo-completo'],
    'easy_apply': True,
    'orden': 'reciente',
  })
  assert 'keywords=python+developer' in url or 'keywords=python%20developer' in url
  assert 'geoId=100876405' in url
  assert 'f_WT=2' in url          # remoto
  assert 'f_TPR=r86400' in url    # 24h
  assert 'f_JT=F' in url          # tiempo-completo
  assert 'f_EA=true' in url
  assert 'sortBy=DD' in url       # reciente


def test_build_linkedin_search_url_fallback_to_location_text() -> None:
  url = build_linkedin_search_url({'cargo': 'backend', 'ubicacion': 'Colombia', 'orden': 'relevancia'})
  assert 'location=Colombia' in url
  assert 'geoId' not in url
  assert 'sortBy=R' in url


def test_build_linkedin_search_url_no_optional_params_when_omitted() -> None:
  url = build_linkedin_search_url({'cargo': 'frontend', 'ubicacion': 'Bogota', 'orden': 'relevancia'})
  assert 'f_WT' not in url
  assert 'f_TPR' not in url
  assert 'f_JT' not in url
  assert 'f_EA' not in url


def test_extractor_extract_offer_links_via_data_occludable_job_id() -> None:
  """Extracts IDs from ALL li[data-occludable-job-id], including empty placeholders.

  LinkedIn sets the attribute on all <li> elements from the initial DOM load.
  extract_offer_links extracts them all; render-based filtering is done via JS
  in _paginate_and_collect, not in BeautifulSoup.
  """
  html = """
  <html><body>
    <ul>
      <li data-occludable-job-id="111"><a href="/jobs/view/111?refId=x">Job A</a></li>
      <li data-occludable-job-id="222"><a href="/jobs/view/222?trackingId=y">Job B</a></li>
      <li data-occludable-job-id="111"><a href="/jobs/view/111">Job A dup</a></li>
      <li data-occludable-job-id="333"><!----></li>
    </ul>
  </body></html>
  """
  extractor = LinkedInExtractor()
  links = extractor.extract_offer_links(html)

  # 333 is an empty placeholder but is included — all IDs are valid
  assert links == [
    'https://www.linkedin.com/jobs/view/111',
    'https://www.linkedin.com/jobs/view/222',
    'https://www.linkedin.com/jobs/view/333',
  ]


def test_extractor_extract_offer_links_fallback_to_anchors() -> None:
  """Fallback: usa anchors /jobs/view/ cuando no hay data-occludable-job-id."""
  html = """
  <html><body>
    <a href="/jobs/view/111?refId=x">Job A</a>
    <a href="https://www.linkedin.com/jobs/view/111?trackingId=y">Job A dup</a>
    <a href="/jobs/view/222">Job B</a>
    <a href="/company/acme">No es oferta</a>
  </body></html>
  """
  extractor = LinkedInExtractor()
  links = extractor.extract_offer_links(html)

  assert links == [
    'https://www.linkedin.com/jobs/view/111',
    'https://www.linkedin.com/jobs/view/222',
  ]


def test_extractor_extract_offer_links_empty_html() -> None:
  extractor = LinkedInExtractor()
  assert extractor.extract_offer_links('<html><body></body></html>') == []


def test_extractor_description_html_to_markdown_converts() -> None:
  html = '<h2>Requisitos</h2><ul><li>Python</li><li>FastAPI</li></ul>'
  extractor = LinkedInExtractor()
  result = extractor.description_html_to_markdown(html)

  assert '## Requisitos' in result
  assert 'Python' in result
  assert 'FastAPI' in result
  assert '<' not in result


def test_extractor_description_html_to_markdown_no_raw_tags() -> None:
  html = '<p>Se busca <strong>backend developer</strong> con experiencia en <em>cloud</em>.</p>'
  extractor = LinkedInExtractor()
  result = extractor.description_html_to_markdown(html)

  assert '<p>' not in result
  assert 'backend developer' in result
  assert 'cloud' in result


def test_detect_block_state_login_required_by_url() -> None:
  extractor = LinkedInExtractor()
  assert extractor.detect_block_state('https://www.linkedin.com/authwall?...', '') == 'login_required'


def test_detect_block_state_login_required_by_body() -> None:
  extractor = LinkedInExtractor()
  state = extractor.detect_block_state('https://www.linkedin.com/jobs/view/123', 'sign in to linkedin to see this')
  assert state == 'login_required'


def test_detect_block_state_captcha_by_body() -> None:
  extractor = LinkedInExtractor()
  state = extractor.detect_block_state('https://www.linkedin.com/jobs/view/123', 'verify you are human')
  assert state == 'captcha'


def test_detect_block_state_none_when_clean() -> None:
  extractor = LinkedInExtractor()
  state = extractor.detect_block_state('https://www.linkedin.com/jobs/view/123', 'Python Developer - ACME Corp')
  assert state is None


def test_linkedin_collector_builds_search_urls() -> None:
  from src.collectors.linkedin import LinkedInCollector

  collector = LinkedInCollector()
  urls = collector.build_search_urls([
    {'cargo': 'python developer', 'geo_id': '100876405', 'modalidades': ['remoto'], 'orden': 'reciente'},
    {'cargo': 'backend engineer', 'ubicacion': 'Bogota', 'orden': 'relevancia'},
  ])

  assert len(urls) == 2
  assert 'keywords=python+developer' in urls[0] or 'keywords=python%20developer' in urls[0]
  assert 'geoId=100876405' in urls[0]
  assert 'sortBy=DD' in urls[0]
  assert 'keywords=backend+engineer' in urls[1] or 'keywords=backend%20engineer' in urls[1]
  assert 'location=Bogota' in urls[1]
