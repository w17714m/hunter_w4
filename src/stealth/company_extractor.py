from __future__ import annotations

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MAX_HTML_CHARS = 4_000

_PROMPT_TEMPLATE = """\
Extract the company name from this LinkedIn job card HTML.
Return ONLY valid JSON with a single key "empresa" containing the company name as a string.
If no company name is found, return {{"empresa": ""}}.
No explanation, no markdown.

HTML:
{html}"""


class CompanyExtractorError(Exception):
    pass


class CompanyExtractor:
    """Extracts company name from LinkedIn job card HTML using a fast non-reasoning LLM.

    Used as fallback when BeautifulSoup selectors fail to find the company name in the
    search result card. Returns empty string on any failure — never propagates exceptions.
    """

    def __init__(
        self,
        base_url: str = 'http://localhost:11434',
        model: str = 'qwen3:8b',
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout_s = timeout_s

    def extract(self, card_html: str) -> str:
        """Return company name extracted from job card HTML, or '' on failure."""
        if not card_html or not card_html.strip():
            return ''
        try:
            cleaned = self._clean_html(card_html)
            prompt = _PROMPT_TEMPLATE.format(html=cleaned)
            raw = self._call_ollama(prompt)
            return self._parse_response(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[CompanyExtractor] Extracción falló: %s', exc)
            return ''

    @staticmethod
    def _clean_html(raw_html: str) -> str:
        soup = BeautifulSoup(raw_html, 'html.parser')
        for tag in soup.find_all(['script', 'style', 'svg', 'noscript']):
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
        response = httpx.post(
            f'{self.base_url}/api/generate',
            json={
                'model': self.model,
                'prompt': prompt,
                'stream': False,
                'format': 'json',
                'options': {'temperature': 0.0},
            },
            timeout=self.timeout_s,
        )
        if response.status_code != 200:
            raise CompanyExtractorError(f'Ollama responded {response.status_code}: {response.text[:200]}')
        data = response.json()
        return str(data.get('response', ''))

    @staticmethod
    def _parse_response(raw: str) -> str:
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        if not raw:
            return ''
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return str(data.get('empresa', '')).strip()
        except json.JSONDecodeError:
            pass
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
                if isinstance(data, dict):
                    return str(data.get('empresa', '')).strip()
            except json.JSONDecodeError:
                pass
        return ''
