from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "List every technology, programming language, framework, library, tool, database, "
    "and cloud platform mentioned in the following job description.\n"
    'Output format: a single JSON array of strings. Example: ["Python", "Docker", "AWS"]\n'
    "No explanation. No markdown. Only the JSON array.\n\n"
    "Job description:\n{descripcion}"
)

_MAX_DESCRIPTION_CHARS = 6000


class LLMSkillExtractorError(Exception):
    pass


class LLMSkillExtractor:
    """Extracts technology skills from a job description using an LLM via Ollama.

    Uses qwen3:8b by default with /no_think to skip chain-of-thought and reduce latency.
    On any failure (network, bad JSON, timeout) returns an empty list so the caller
    can fall back to the original regex-based logic.
    """

    def __init__(
        self,
        base_url: str = 'http://localhost:11434',
        model: str = 'deepseek-r1:14b',
        timeout_s: float = 48,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout_s = timeout_s

    def extract(self, descripcion_md: str) -> list[str]:
        """Return a list of technology names found in the description.

        Returns an empty list on any error — callers must handle this as a fallback signal.
        """
        if not descripcion_md or not descripcion_md.strip():
            return []
        try:
            prompt = _PROMPT_TEMPLATE.format(
                descripcion=descripcion_md[:_MAX_DESCRIPTION_CHARS]
            )
            raw = self._call_ollama(prompt)
            return self._parse_response(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[LLMSkillExtractor] Extraction failed, using fallback: %s', exc)
            return []

    def _call_ollama(self, prompt: str) -> str:
        # /api/chat is used instead of /api/generate because think=false is a
        # top-level parameter only honoured by the chat endpoint (known Ollama bug
        # where /api/generate ignores think=false in options).
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
            raise LLMSkillExtractorError(
                f'Cannot connect to Ollama at {self.base_url}: {exc}'
            ) from exc

        if response.status_code != 200:
            raise LLMSkillExtractorError(
                f'Ollama responded {response.status_code}: {response.text[:200]}'
            )

        data = response.json()
        return data.get('message', {}).get('content', '')

    @staticmethod
    def _parse_response(raw: str) -> list[str]:
        """Extract a JSON array from the LLM response.

        The model may wrap the array in an object like {"skills": [...]} or return
        it directly as [...].  Strips <think>...</think> blocks emitted by reasoning
        models before parsing.
        """
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        if not raw:
            return []

        # Try direct array parse first
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s).strip() for s in parsed if str(s).strip()]
            # Model returned {"skills": [...]} or similar wrapper
            if isinstance(parsed, dict):
                for val in parsed.values():
                    if isinstance(val, list):
                        return [str(s).strip() for s in val if str(s).strip()]
        except json.JSONDecodeError:
            pass

        # Fallback: find the first [...] block in the text
        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start:end + 1])
                if isinstance(parsed, list):
                    return [str(s).strip() for s in parsed if str(s).strip()]
            except json.JSONDecodeError:
                pass

        logger.warning('[LLMSkillExtractor] Could not parse response as JSON array: %s', raw[:200])
        return []
