from __future__ import annotations

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MAX_HTML_CHARS = 12_000

_PROMPT_TEMPLATE = """\
You are analyzing a LinkedIn job posting page HTML. Your goal is to extract the full job description.

LinkedIn sometimes truncates the description and hides a "show more" button. This button may have \
any of these visible texts (in any language): "show more", "ver más", "…more", "...more", "see more", \
"mostrar más", "más", "expand", or similar. It is often a <button> or <span> with \
data-testid, aria-label, or data-control-name attributes.

Step 1: Check if the job description text is already fully visible in the HTML. \
If so, return it in "description_text" and leave "expand_selector" empty.

Step 2: If the description appears truncated or a "show more" button is present, \
return an empty "description_text" and provide in "expand_selector" the most stable CSS selector \
for that button. Prefer selectors using data-* or aria-* attributes over class names \
(e.g. [data-testid="show-more-btn"], [aria-label="ver más"], [data-control-name="show_more"]). \
If the button has no stable attributes, use its visible text with :has-text() or the element type \
and position (e.g. button:last-of-type in the description section).

Respond ONLY with valid JSON — no explanation, no markdown, no extra text:
{{"description_text": "full description text or empty string", "expand_selector": "CSS selector or empty string"}}

HTML:
{html}"""


class HTMLDescriptionExtractorError(Exception):
    pass


class HTMLDescriptionExtractor:
    """Extracts LinkedIn job descriptions from raw page HTML using a reasoning LLM via Ollama.

    Used as a fallback when all hardcoded CSS selectors in DESCRIPTION_SELECTORS fail.
    The LLM either returns the description text directly or identifies a stable CSS selector
    (preferring data-* and aria-* attributes) for the expand button.
    On any failure (network, bad JSON, timeout) returns empty strings so the caller
    can fall back to the original empty_description behavior without disruption.
    """

    def __init__(
        self,
        base_url: str = 'http://localhost:11434',
        model: str = 'deepseek-r1:14b',
        timeout_s: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout_s = timeout_s

    def extract(self, raw_html: str) -> dict[str, str]:
        """Return {'description_text': ..., 'expand_selector': ...}.

        Returns {'description_text': '', 'expand_selector': ''} on any error.
        Callers must treat empty strings as "fallback not available".
        """
        empty: dict[str, str] = {'description_text': '', 'expand_selector': ''}
        if not raw_html or not raw_html.strip():
            logger.warning('[HTMLExtractor] HTML de entrada vacío — abortando')
            return empty
        try:
            logger.info('[HTMLExtractor] Limpiando HTML (raw_len=%d)', len(raw_html))
            cleaned = self._clean_html(raw_html)
            logger.info('[HTMLExtractor] HTML limpio listo (cleaned_len=%d) — construyendo prompt', len(cleaned))
            prompt = _PROMPT_TEMPLATE.format(html=cleaned)
            raw_response = self._call_ollama(prompt)
            result = self._parse_response(raw_response)
            logger.info('[HTMLExtractor] Parseo completado | description_text_len=%d | expand_selector="%s"', len(result.get('description_text', '')), result.get('expand_selector', ''))
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning('[HTMLExtractor] Extracción falló: %s', exc)
            return empty

    @staticmethod
    def _clean_html(raw_html: str) -> str:
        """Strip noise from HTML to reduce token count before sending to LLM.

        Removes tags that are never relevant to the description (scripts, styles, nav).
        Removes class/id/style attributes that LinkedIn rotates intentionally.
        Preserves data-* and aria-* attributes which are more stable and help
        the LLM build a reliable CSS selector.
        """
        soup = BeautifulSoup(raw_html, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'svg', 'noscript', 'header', 'nav', 'footer']):
            tag.decompose()

        _STABLE_ATTRS = frozenset({'role', 'type', 'name'})
        for tag in soup.find_all(True):
            for attr in list(tag.attrs):
                if attr in ('class', 'id', 'style'):
                    del tag[attr]
                elif not (attr.startswith('data-') or attr.startswith('aria-') or attr in _STABLE_ATTRS):
                    del tag[attr]

        return str(soup)[:_MAX_HTML_CHARS]

    def _call_ollama(self, prompt: str) -> str:
        # /api/chat is used instead of /api/generate because think=False is a
        # top-level parameter only honoured by the chat endpoint (known Ollama bug
        # where /api/generate ignores think=False in options).
        logger.info('[HTMLExtractor] Enviando solicitud a Ollama | model=%s | url=%s/api/chat | prompt_len=%d', self.model, self.base_url, len(prompt))
        try:
            response = httpx.post(
                f'{self.base_url}/api/chat',
                json={
                    'model': self.model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'stream': False,
                    'think': False,
                    'options': {'temperature': 0.0},
                },
                timeout=self.timeout_s,
            )
        except httpx.TransportError as exc:
            logger.error('[HTMLExtractor] Error de conexión con Ollama en %s: %s', self.base_url, exc)
            raise HTMLDescriptionExtractorError(
                f'Cannot connect to Ollama at {self.base_url}: {exc}'
            ) from exc

        logger.info('[HTMLExtractor] Respuesta de Ollama | status=%d', response.status_code)
        if response.status_code != 200:
            logger.error('[HTMLExtractor] Ollama devolvió error %d: %s', response.status_code, response.text[:200])
            raise HTMLDescriptionExtractorError(
                f'Ollama responded {response.status_code}: {response.text[:200]}'
            )

        data = response.json()
        content = data.get('message', {}).get('content', '')
        logger.info('[HTMLExtractor] Contenido recibido de Ollama (primeros 200 chars): %s', content[:200].replace('\n', ' '))
        return content

    @staticmethod
    def _parse_response(raw: str) -> dict[str, str]:
        """Parse the LLM JSON response. Strips <think>...</think> blocks first."""
        empty: dict[str, str] = {'description_text': '', 'expand_selector': ''}

        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        if not raw:
            return empty

        def _extract(parsed: object) -> dict[str, str] | None:
            if isinstance(parsed, dict):
                return {
                    'description_text': str(parsed.get('description_text', '')).strip(),
                    'expand_selector': str(parsed.get('expand_selector', '')).strip(),
                }
            return None

        try:
            result = _extract(json.loads(raw))
            if result is not None:
                return result
        except json.JSONDecodeError:
            pass

        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end > start:
            try:
                result = _extract(json.loads(raw[start:end + 1]))
                if result is not None:
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning('[HTMLDescriptionExtractor] Could not parse LLM response as JSON: %s', raw[:200])
        return empty
