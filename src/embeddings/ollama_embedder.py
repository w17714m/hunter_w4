from __future__ import annotations

import httpx


class OllamaEmbedderError(Exception):
  pass


class OllamaEmbedder:
  """Cliente de embeddings contra la API /api/embeddings de Ollama.

  Lanza OllamaEmbedderError en cualquier fallo de red o respuesta inesperada
  — nunca silencia errores.
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
    """Retorna el vector de embedding para un texto."""
    return self._call(text)

  def embed_batch(self, texts: list[str]) -> list[list[float]]:
    """Retorna una lista de vectores, uno por texto."""
    return [self._call(t) for t in texts]

  def _call(self, text: str) -> list[float]:
    if not text or not text.strip():
      raise OllamaEmbedderError('El texto para embeddings no puede estar vacío')
    try:
      response = httpx.post(
        f'{self.base_url}/api/embeddings',
        json={'model': self.model, 'prompt': text},
        timeout=self.timeout_s,
      )
    except httpx.TransportError as exc:
      raise OllamaEmbedderError(f'No se pudo conectar a Ollama en {self.base_url}: {exc}') from exc

    if response.status_code != 200:
      raise OllamaEmbedderError(
        f'Ollama respondió {response.status_code}: {response.text[:200]}'
      )

    data = response.json()
    embedding: list[float] | None = data.get('embedding')
    if not embedding:
      raise OllamaEmbedderError(f'Ollama no devolvió campo "embedding". Respuesta: {data}')

    return embedding
