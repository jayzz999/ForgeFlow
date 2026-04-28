import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").lower()
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_FAST_MODEL: str = os.getenv("GROQ_FAST_MODEL", GROQ_MODEL)

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_FAST_MODEL: str = os.getenv("GEMINI_FAST_MODEL", GEMINI_MODEL)
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "local").lower()
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_APP_TOKEN: str = os.getenv("SLACK_APP_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_NOTIFICATION_CHANNEL: str = os.getenv("SLACK_NOTIFICATION_CHANNEL", "#forgeflow-alerts")

    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    SPECS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "discovery", "specs")

    SANDBOX_TIMEOUT: int = int(os.getenv("SANDBOX_TIMEOUT", "60"))
    MAX_DEBUG_ATTEMPTS: int = 3

    # ── Security ───────────────────────────────────────────────────
    FORGEFLOW_ADMIN_TOKEN: str = os.getenv("FORGEFLOW_ADMIN_TOKEN", "")
    FORGEFLOW_ALLOW_UNAUTH_DANGEROUS: bool = os.getenv("FORGEFLOW_ALLOW_UNAUTH_DANGEROUS", "0") in ("1", "true", "yes")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./forgeflow.db")


settings = Settings()
