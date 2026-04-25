import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_FAST_MODEL: str = "gemini-2.5-flash"

    # ── Genesis LLM provider ───────────────────────────────────────
    # GENESIS_LLM_PROVIDER=groq  → free Groq/Llama (dev/testing)
    # GENESIS_LLM_PROVIDER=gemini → Gemini 2.5 Flash (demo/prod)
    GENESIS_LLM_PROVIDER: str = os.getenv("GENESIS_LLM_PROVIDER", "gemini")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── Genesis dreaming throttle ──────────────────────────────────
    # GENESIS_DREAMING=0  → disable idle dreaming entirely (zero extra cost)
    # GENESIS_IDLE_DREAM_AFTER_S → seconds idle before dreaming (default 3600)
    GENESIS_DREAMING: bool = os.getenv("GENESIS_DREAMING", "1") not in ("0", "false", "no")
    GENESIS_IDLE_DREAM_AFTER_S: int = int(os.getenv("GENESIS_IDLE_DREAM_AFTER_S", "3600"))

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
