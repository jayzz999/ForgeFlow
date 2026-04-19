"""Shared fixtures for Genesis tests."""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_storage(monkeypatch):
    """Each test gets its own organisms/ directory."""
    d = Path(tempfile.mkdtemp(prefix="genesis_test_"))
    monkeypatch.setenv("GENESIS_STORAGE", str(d))
    # Force the store module to re-read the env var
    from backend.genesis import store
    monkeypatch.setattr(store, "_BASE", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class FakeLLM:
    """Records prompts, returns canned JSON responses in order."""
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[dict] = []

    async def __call__(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int = 8000,
    ) -> str:
        # Mirrors backend.shared.gemini_client.generate_text exactly so tests
        # exercise the same call shape production code uses.
        self.prompts.append({
            "prompt": prompt,
            "system": system,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if not self.responses:
            raise RuntimeError("FakeLLM ran out of canned responses")
        return self.responses.pop(0)


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the gemini_client.generate_text so no real API calls happen."""
    fake = FakeLLM([])
    from backend.shared import gemini_client
    monkeypatch.setattr(gemini_client, "generate_text", fake)
    return fake
