from fastapi.testclient import TestClient

from backend.main import app
from backend.shared.config import settings


def test_provider_status_does_not_expose_secret_values(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "secret-groq-key")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FAST_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "secret-gemini-key")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")

    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["llm"]["provider"] == "groq"
    assert data["llm"]["configured"] is True
    assert data["llm"]["model"] == "llama-3.3-70b-versatile"
    assert data["embeddings"] == {
        "provider": "local",
        "configured": True,
        "model": "local",
    }
    assert data["services"]["slack"]["configured"] is True
    serialized = response.text
    assert "secret-openai-key" not in serialized
    assert "secret-groq-key" not in serialized
    assert "secret-gemini-key" not in serialized
    assert "xoxb-secret" not in serialized
