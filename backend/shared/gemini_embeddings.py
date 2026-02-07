"""Gemini embedding function for ChromaDB.

Replaces OpenAI's text-embedding-3-small with Gemini's gemini-embedding-001.
"""

from google import genai


class GeminiEmbeddingFunction:
    """ChromaDB-compatible embedding function using Gemini."""

    def __init__(self, api_key: str, model_name: str = "gemini-embedding-001"):
        self._client = genai.Client(api_key=api_key)
        self._model = model_name

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Embed a list of texts using Gemini."""
        result = self._client.models.embed_content(
            model=self._model,
            contents=input,
        )
        return [e.values for e in result.embeddings]
