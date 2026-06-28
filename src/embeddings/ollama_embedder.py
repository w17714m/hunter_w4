from __future__ import annotations

import httpx


class OllamaEmbedderError(Exception):
  pass


class OllamaEmbedder:
  """Embeddings client for the Ollama /api/embeddings endpoint.

  Raises OllamaEmbedderError on any network failure or unexpected response
  — never silences errors.
  """

  def __init__(
    self,
    base_url: str = 'http://localhost:11434',
    model: str = 'nomic-embed-text',
    timeout_s: float = 60.0,
  ) -> None:
    self.base_url = base_url.rstrip('/')
    self.model = model
    self.timeout_s = timeout_s

  def embed(self, text: str) -> list[float]:
    """Return the embedding vector for a text."""
    return self._call(text)

  def embed_batch(self, texts: list[str]) -> list[list[float]]:
    """Return a list of vectors, one per text."""
    return [self._call(t) for t in texts]

  def _call(self, text: str) -> list[float]:
    if not text or not text.strip():
      raise OllamaEmbedderError('Text for embeddings cannot be empty')
    try:
      response = httpx.post(
        f'{self.base_url}/api/embeddings',
        json={'model': self.model, 'prompt': text},
        timeout=self.timeout_s,
      )
    except httpx.TransportError as exc:
      raise OllamaEmbedderError(f'Could not connect to Ollama at {self.base_url}: {exc}') from exc

    if response.status_code != 200:
      raise OllamaEmbedderError(
        f'Ollama responded {response.status_code}: {response.text[:200]}'
      )

    data = response.json()
    embedding: list[float] | None = data.get('embedding')
    if not embedding:
      raise OllamaEmbedderError(f'Ollama did not return "embedding" field. Response: {data}')

    return embedding
