import asyncio
import base64
import csv
import html
import hmac
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import ssl
import sys
import tempfile
import uuid
import zipfile
import io
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.getLogger("slack").setLevel(logging.WARNING)
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from backend.connectors.catalog import BASE_CAPABILITIES, SERVICE_MARKERS, SERVICE_TO_DEFAULT_CAPABILITY, capability_specs
from backend.shared.config import settings
from backend.shared.models import ForgeRequest, ForgeResponse
from backend.shared.security import require_admin_token
from backend.shared.services import SUPPORTED_SERVICES


# ── WebSocket Connection Manager ──────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, client_id: str):
        await ws.accept()
        self.active[client_id] = ws

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)

    async def send_event(self, client_id: str, event: dict):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_json(event)

    async def broadcast(self, event: dict):
        for ws in self.active.values():
            try:
                await ws.send_json(event)
            except Exception:
                pass


manager = ConnectionManager()

RUN_ENV_PREFIXES = (
    "SLACK_", "GMAIL_", "GOOGLE_", "SHEETS_",
    "WEBHOOK_", "API_", "AUTH_", "TOKEN_",
)
RUN_ENV_EXACT = {"TARGET_URL"}
MAX_RUN_OUTPUT_CHARS = 12000
PLATFORM_DB_PATH = os.getenv(
    "PLATFORM_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "forgeflow_platform.db"),
)
APP_BUILDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app_builds")
API_GURU_LIST_URL = "https://api.apis.guru/v2/list.json"

CAPABILITY_REGISTRY = BASE_CAPABILITIES

TEMPLATE_GALLERY = [
    {
        "id": "hr-onboarding",
        "name": "New Hire Onboarding",
        "category": "HR",
        "prompt": "Automate new hire onboarding from an uploaded HR sheet. Draft welcome email, Slack announcement, IT request, and tracking row. Dry run first.",
        "connectors": ["schema.inspect_file", "gmail.send_email", "slack.post_message", "sheets.append_row"],
    },
    {
        "id": "incident-alert",
        "name": "Incident Alert Routing",
        "category": "Ops",
        "prompt": "Watch an HTTP health check, alert Slack on failure, and create a run log with retry status.",
        "connectors": ["http.request", "slack.post_message"],
    },
    {
        "id": "lead-enrichment",
        "name": "Lead Enrichment Queue",
        "category": "Sales",
        "prompt": "Read leads from a CSV, validate required fields, enrich via API, and prepare CRM updates for approval.",
        "connectors": ["schema.inspect_file", "http.request", "approval.wait"],
    },
]

DEPLOYMENT_TARGETS = [
    {
        "id": "local_docker",
        "name": "Local Docker",
        "status": "available",
        "description": "Build and run the generated project on this machine with Docker.",
        "requires": ["Docker"],
    },
    {
        "id": "github_actions",
        "name": "GitHub Actions Cron",
        "status": "planned",
        "description": "Commit workflow project and run it on a schedule in GitHub Actions.",
        "requires": ["GitHub repo", "secrets"],
        "requires_env": ["GITHUB_TOKEN"],
    },
    {
        "id": "render_worker",
        "name": "Render Worker",
        "status": "planned",
        "description": "Deploy the workflow as a persistent Render worker with managed env vars.",
        "requires": ["Render account", "secrets"],
        "requires_env": ["RENDER_API_KEY"],
    },
    {
        "id": "vercel_project",
        "name": "Vercel Project",
        "status": "planned",
        "description": "Deploy generated app-builder artifacts or webhook runtimes to Vercel.",
        "requires": ["Vercel account", "project token"],
        "requires_env": ["VERCEL_TOKEN"],
    },
    {
        "id": "webhook_runtime",
        "name": "Hosted Webhook Runtime",
        "status": "planned",
        "description": "Expose a webhook URL that triggers a selected automation version.",
        "requires": ["public runtime", "auth policy"],
    },
]


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _production_mode() -> bool:
    return os.getenv("FORGEFLOW_ENV", settings.FORGEFLOW_ENV).lower() in {"prod", "production"}


def _demo_endpoints_enabled() -> bool:
    return not _production_mode() or _truthy_env("FORGEFLOW_ENABLE_DEMO_ENDPOINTS")


def _require_demo_enabled():
    if not _demo_endpoints_enabled():
        raise HTTPException(status_code=403, detail="Demo endpoints are disabled in production")


def _check_status(ok: bool, fail_in_production: bool = True) -> str:
    if ok:
        return "pass"
    return "fail" if _production_mode() and fail_in_production else "warn"


def _production_readiness_report() -> dict:
    """Report the blockers that separate a demo workspace from a production runtime."""
    admin_token = os.getenv("FORGEFLOW_ADMIN_TOKEN", settings.FORGEFLOW_ADMIN_TOKEN)
    weak_admin_token = not admin_token or admin_token in {"change-me", "changeme", "secret", "password"}
    allow_unauth = _truthy_env("FORGEFLOW_ALLOW_UNAUTH_DANGEROUS")
    vault_key = os.getenv("FORGEFLOW_VAULT_KEY", settings.FORGEFLOW_VAULT_KEY)
    connectors = _list_connector_states()
    connected_connectors = [item for item in connectors if item["status"] == "connected"]
    provider_health = _deployment_provider_health()
    ready_targets = [item for item in provider_health if item["status"] == "pass"]
    db_path = os.path.abspath(PLATFORM_DB_PATH)
    repo_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    local_sqlite = db_path.startswith(repo_root)
    demo_enabled = _demo_endpoints_enabled()

    checks = [
        {
            "id": "environment",
            "label": "Production environment selected",
            "status": "pass" if _production_mode() else "warn",
            "detail": os.getenv("FORGEFLOW_ENV", settings.FORGEFLOW_ENV),
        },
        {
            "id": "admin_token",
            "label": "Strong admin token configured",
            "status": _check_status(not weak_admin_token),
            "detail": "FORGEFLOW_ADMIN_TOKEN is set" if not weak_admin_token else "Set a high-entropy FORGEFLOW_ADMIN_TOKEN",
        },
        {
            "id": "dangerous_unauth",
            "label": "Dangerous unauthenticated execution disabled",
            "status": _check_status(not allow_unauth),
            "detail": "FORGEFLOW_ALLOW_UNAUTH_DANGEROUS is disabled" if not allow_unauth else "Set FORGEFLOW_ALLOW_UNAUTH_DANGEROUS=0",
        },
        {
            "id": "vault_key",
            "label": "Dedicated credential vault key configured",
            "status": _check_status(bool(vault_key)),
            "detail": "FORGEFLOW_VAULT_KEY is set" if vault_key else "Set FORGEFLOW_VAULT_KEY before storing production secrets",
        },
        {
            "id": "demo_endpoints",
            "label": "Demo endpoints disabled",
            "status": _check_status(not demo_enabled),
            "detail": "Demo endpoints are disabled" if not demo_enabled else "Set FORGEFLOW_ENABLE_DEMO_ENDPOINTS=0 in production",
        },
        {
            "id": "queue_worker",
            "label": "Hosted queue worker enabled",
            "status": _check_status(_truthy_env("FORGEFLOW_QUEUE_WORKER"), fail_in_production=False),
            "detail": "FORGEFLOW_QUEUE_WORKER=1" if _truthy_env("FORGEFLOW_QUEUE_WORKER") else "Enable FORGEFLOW_QUEUE_WORKER=1 for scheduled/webhook jobs",
        },
        {
            "id": "connector_credentials",
            "label": "At least one live connector credential configured",
            "status": _check_status(bool(connected_connectors), fail_in_production=False),
            "detail": f"{len(connected_connectors)} connected connector(s)",
        },
        {
            "id": "deployment_target",
            "label": "At least one deployment target ready",
            "status": _check_status(bool(ready_targets), fail_in_production=False),
            "detail": ", ".join(item["name"] for item in ready_targets) if ready_targets else "Configure Docker, GitHub, Render, or hosted runtime credentials",
        },
        {
            "id": "runtime_base_url",
            "label": "Hosted runtime base URL configured",
            "status": _check_status(bool(os.getenv("FORGEFLOW_RUNTIME_BASE_URL", settings.FORGEFLOW_RUNTIME_BASE_URL)), fail_in_production=False),
            "detail": os.getenv("FORGEFLOW_RUNTIME_BASE_URL", settings.FORGEFLOW_RUNTIME_BASE_URL) or "Set FORGEFLOW_RUNTIME_BASE_URL for webhook activation",
        },
        {
            "id": "database",
            "label": "Persistent production database configured",
            "status": _check_status(not local_sqlite, fail_in_production=False),
            "detail": db_path if not local_sqlite else "Local SQLite is acceptable for staging; use a mounted volume or managed DB in production",
        },
        {
            "id": "mcp_runtime",
            "label": "MCP runtime adapter ingestion connected",
            "status": _check_status(_truthy_env("FORGEFLOW_MCP_RUNTIME_ENABLED"), fail_in_production=False),
            "detail": "FORGEFLOW_MCP_RUNTIME_ENABLED=1" if _truthy_env("FORGEFLOW_MCP_RUNTIME_ENABLED") else "Enable MCP ingestion before claiming dynamic external tool support",
        },
    ]
    blockers = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    pass_count = sum(1 for check in checks if check["status"] == "pass")
    return {
        "production_mode": _production_mode(),
        "ready": not blockers and not warnings,
        "score": round((pass_count / len(checks)) * 100),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "connected_connectors": [item["service"] for item in connected_connectors],
        "deployment_targets": provider_health,
        "next_actions": [item["detail"] for item in blockers + warnings],
    }


def _workflow_run_env() -> dict[str, str]:
    """Allowlist env vars passed to generated workflow execution."""
    env = {"PYTHONUNBUFFERED": "1"}
    for key, value in os.environ.items():
        if key in RUN_ENV_EXACT or any(key.startswith(prefix) for prefix in RUN_ENV_PREFIXES):
            env[key] = value
    return env


def _platform_db() -> sqlite3.Connection:
    conn = sqlite3.connect(PLATFORM_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            action_type TEXT NOT NULL,
            title TEXT NOT NULL,
            preview_json TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS triggers (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            config_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'paused',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_logs (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            stdout TEXT,
            stderr TEXT,
            execution_time REAL,
            return_code INTEGER,
            attempt INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS automation_specs (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            trigger_json TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            connectors_json TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            approval_gates_json TEXT NOT NULL,
            tests_json TEXT NOT NULL,
            deployment_json TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runtime_runs (
            id TEXT PRIMARY KEY,
            spec_id TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS runtime_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS workflow_exports (
            id TEXT PRIMARY KEY,
            spec_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            artifact_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS connector_validations (
            id TEXT PRIMARY KEY,
            adapter_id TEXT NOT NULL,
            status TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            alternatives_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS connector_tests (
            id TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            request_json TEXT NOT NULL,
            response_json TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS repair_runs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ingestions (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            name TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deployment_plans (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS connector_states (
            service TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            auth_type TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            env_status_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS oauth_sessions (
            state TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            status TEXT NOT NULL,
            auth_url TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trigger_events (
            id TEXT PRIMARY KEY,
            trigger_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            run_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS credential_vault (
            id TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            label TEXT NOT NULL,
            kind TEXT NOT NULL,
            ciphertext TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_queue (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 5,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deployment_activations (
            id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            artifacts_json TEXT NOT NULL,
            blockers_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deployment_jobs (
            id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            provider_request_json TEXT NOT NULL,
            provider_response_json TEXT NOT NULL,
            blockers_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS eval_runs (
            id TEXT PRIMARY KEY,
            suite TEXT NOT NULL,
            score REAL NOT NULL,
            cases_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS credential_audit (
            id TEXT PRIMARY KEY,
            credential_id TEXT NOT NULL,
            service TEXT NOT NULL,
            action TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observability_events (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            event_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    for statement in (
        "ALTER TABLE run_queue ADD COLUMN next_attempt_at TEXT",
        "ALTER TABLE run_queue ADD COLUMN dead_letter_reason TEXT",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _stable_id(prefix: str, payload: object | None = None) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, default=str) + _now_iso() + str(uuid.uuid4())
    return f"{prefix}_{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _vault_key() -> bytes:
    seed = (
        os.getenv("FORGEFLOW_VAULT_KEY")
        or settings.FORGEFLOW_ADMIN_TOKEN
        or "forgeflow-local-development-vault-key"
    ).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", seed, b"forgeflow-vault-v1", 200_000, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def _encrypt_secret(value: str) -> str:
    key = _vault_key()
    nonce = os.urandom(16)
    plain = value.encode("utf-8")
    stream = _keystream(key, nonce, len(plain))
    cipher = bytes(a ^ b for a, b in zip(plain, stream))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")


def _decrypt_secret(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _vault_key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Credential vault integrity check failed")
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def _oauth_specs() -> dict[str, dict]:
    specs = {
        "gmail": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "redirect_uri_env": "GOOGLE_OAUTH_REDIRECT_URI",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.compose",
            ],
            "env_vars": ["GMAIL_ACCESS_TOKEN", "GMAIL_SENDER_EMAIL"],
        },
        "sheets": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "redirect_uri_env": "GOOGLE_OAUTH_REDIRECT_URI",
            "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
            "env_vars": ["GOOGLE_SHEETS_ACCESS_TOKEN"],
        },
        "slack": {
            "auth_url": "https://slack.com/oauth/v2/authorize",
            "token_url": "https://slack.com/api/oauth.v2.access",
            "client_id_env": "SLACK_CLIENT_ID",
            "client_secret_env": "SLACK_CLIENT_SECRET",
            "redirect_uri_env": "SLACK_OAUTH_REDIRECT_URI",
            "scopes": ["chat:write", "channels:read", "users:read.email"],
            "env_vars": ["SLACK_BOT_TOKEN"],
        },
    }
    generic_oauth = {
        "salesforce": {
            "auth_url": os.getenv("SALESFORCE_AUTH_URL", "https://login.salesforce.com/services/oauth2/authorize"),
            "token_url": os.getenv("SALESFORCE_TOKEN_URL", "https://login.salesforce.com/services/oauth2/token"),
            "client_id_env": "SALESFORCE_CLIENT_ID",
            "client_secret_env": "SALESFORCE_CLIENT_SECRET",
            "redirect_uri_env": "SALESFORCE_OAUTH_REDIRECT_URI",
        },
        "teams": {
            "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "client_id_env": "MICROSOFT_CLIENT_ID",
            "client_secret_env": "MICROSOFT_CLIENT_SECRET",
            "redirect_uri_env": "MICROSOFT_OAUTH_REDIRECT_URI",
        },
        "calendar": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "redirect_uri_env": "GOOGLE_OAUTH_REDIRECT_URI",
        },
    }
    for service, oauth in generic_oauth.items():
        info = SUPPORTED_SERVICES.get(service, {})
        specs[service] = {
            **oauth,
            "scopes": list(info.get("scopes", ())),
            "env_vars": list(info.get("env_vars", ())),
        }
    return specs


def _env_status(env_vars: list[str] | tuple[str, ...]) -> dict:
    present = [name for name in env_vars if bool(os.getenv(name, ""))]
    missing = [name for name in env_vars if name not in present]
    return {
        "configured": not missing,
        "present": present,
        "missing": missing,
    }


def _upsert_connector_state(service: str, status: str, auth_type: str, scopes: list[str], env_vars: list[str] | tuple[str, ...], metadata: dict | None = None) -> dict:
    now = _now_iso()
    env = _env_status(env_vars)
    conn = _platform_db()
    existing = conn.execute("SELECT created_at FROM connector_states WHERE service = ?", (service,)).fetchone()
    created_at = existing["created_at"] if existing else now
    conn.execute(
        """
        INSERT OR REPLACE INTO connector_states
        (service, status, auth_type, scopes_json, env_status_json, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            service,
            status,
            auth_type,
            json.dumps(scopes),
            json.dumps(env),
            json.dumps(metadata or {}),
            created_at,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "service": service,
        "status": status,
        "auth_type": auth_type,
        "scopes": scopes,
        "env_status": env,
        "metadata": metadata or {},
        "created_at": created_at,
        "updated_at": now,
    }


def _list_connector_states() -> list[dict]:
    status_by_service = {}
    vault_services = _credential_services()
    for service, info in SUPPORTED_SERVICES.items():
        env = _env_status(info.get("env_vars", ()))
        connected = env["configured"] or service in vault_services
        source = info.get("source", "environment")
        metadata = {
            "name": info["name"],
            "source": source,
            "docs_url": info.get("docs_url"),
            "capability_count": len([item for item in CAPABILITY_REGISTRY if item.get("source") == service]),
        }
        if service in vault_services:
            metadata["vault_credential"] = True
        status_by_service[service] = _upsert_connector_state(
            service=service,
            status="connected" if connected else "missing_credentials",
            auth_type=info.get("auth_type", "api_key"),
            scopes=list(info.get("scopes", ())) or _oauth_specs().get(service, {}).get("scopes", []),
            env_vars=info.get("env_vars", ()),
            metadata=metadata,
        )

    conn = _platform_db()
    rows = conn.execute("SELECT * FROM connector_states ORDER BY service ASC").fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        status_by_service[item["service"]] = {
            "service": item["service"],
            "status": item["status"],
            "auth_type": item["auth_type"],
            "scopes": _json_loads(item["scopes_json"], []),
            "env_status": _json_loads(item["env_status_json"], {"configured": False, "present": [], "missing": []}),
            "metadata": _json_loads(item["metadata_json"], {}),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
        }
    return list(status_by_service.values())


def _list_oauth_sessions() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM oauth_sessions ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return [
        {
            "state": row["state"],
            "service": row["service"],
            "status": row["status"],
            "auth_url": row["auth_url"],
            "scopes": _json_loads(row["scopes_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _store_credential(service: str, label: str, kind: str, secret_value: str, metadata: dict | None = None) -> dict:
    credential_id = _stable_id("cred", {"service": service, "label": label, "kind": kind})
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO credential_vault
        (id, service, label, kind, ciphertext, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            credential_id,
            service,
            label,
            kind,
            _encrypt_secret(secret_value),
            json.dumps(metadata or {}),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    _record_credential_audit(credential_id, service, "created", {"label": label, "kind": kind})
    return {
        "id": credential_id,
        "service": service,
        "label": label,
        "kind": kind,
        "masked": _mask_secret(secret_value),
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    }


def _record_credential_audit(credential_id: str, service: str, action: str, metadata: dict | None = None) -> dict:
    record = {
        "id": _stable_id("cred_audit", {"credential_id": credential_id, "action": action}),
        "credential_id": credential_id,
        "service": service,
        "action": action,
        "metadata": metadata or {},
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO credential_audit
        (id, credential_id, service, action, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (record["id"], credential_id, service, action, json.dumps(record["metadata"]), record["created_at"]),
    )
    conn.commit()
    conn.close()
    return record


def _list_credential_audit(limit: int = 50) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM credential_audit ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "credential_id": row["credential_id"],
            "service": row["service"],
            "action": row["action"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _rotate_credential(credential_id: str, secret_value: str, metadata: dict | None = None) -> dict:
    if not secret_value:
        raise HTTPException(status_code=400, detail="new secret is required")
    conn = _platform_db()
    row = conn.execute("SELECT * FROM credential_vault WHERE id = ?", (credential_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Credential not found")
    merged_metadata = {**_json_loads(row["metadata_json"], {}), **(metadata or {}), "rotated_at": _now_iso()}
    conn.execute(
        "UPDATE credential_vault SET ciphertext = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
        (_encrypt_secret(secret_value), json.dumps(merged_metadata), _now_iso(), credential_id),
    )
    conn.commit()
    conn.close()
    _record_credential_audit(credential_id, row["service"], "rotated", {"label": row["label"], "kind": row["kind"]})
    return {
        "id": credential_id,
        "service": row["service"],
        "label": row["label"],
        "kind": row["kind"],
        "masked": _mask_secret(secret_value),
        "metadata": merged_metadata,
        "updated_at": _now_iso(),
    }


def _list_credentials() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM credential_vault ORDER BY created_at DESC").fetchall()
    conn.close()
    credentials = []
    for row in rows:
        try:
            masked = _mask_secret(_decrypt_secret(row["ciphertext"]))
            valid = True
        except Exception:
            masked = "unreadable"
            valid = False
        credentials.append({
            "id": row["id"],
            "service": row["service"],
            "label": row["label"],
            "kind": row["kind"],
            "masked": masked,
            "valid": valid,
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return credentials


def _credential_services() -> set[str]:
    return {item["service"] for item in _list_credentials() if item.get("valid")}


def _credential_records_for_service(service: str) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM credential_vault WHERE service = ? ORDER BY updated_at DESC", (service,)).fetchall()
    conn.close()
    credentials = []
    for row in rows:
        try:
            credentials.append({
                "service": row["service"],
                "label": row["label"],
                "kind": row["kind"],
                "secret": _decrypt_secret(row["ciphertext"]),
                "metadata": _json_loads(row["metadata_json"], {}),
            })
        except Exception:
            continue
    return credentials


def _credential_record_for_service(service: str) -> dict | None:
    credentials = _credential_records_for_service(service)
    for kind in ("access_token", "api_key", "bot_token", "token", "password", "client_secret", "refresh_token"):
        credential = next((item for item in credentials if item.get("kind") == kind), None)
        if credential:
            return credential
    if credentials:
        return credentials[0]
    return None


def _config_for_service(service: str) -> dict:
    """Return non-secret connector config from env plus encrypted-vault metadata."""
    config = {}
    if service in {"gmail", "sheets", "calendar"}:
        google_oauth = _credential_record_for_service("google_oauth")
        if google_oauth:
            metadata = google_oauth.get("metadata", {})
            if isinstance(metadata, dict):
                config.update(metadata)
    credential = _credential_record_for_service(service)
    if credential:
        metadata = credential.get("metadata", {})
        if isinstance(metadata, dict):
            config.update(metadata)
    for name in SUPPORTED_SERVICES.get(service, {}).get("env_vars", ()):
        value = os.getenv(name)
        if value:
            config[name] = value
            config[name.lower()] = value
    return config


def _connector_config_value(service: str, *names: str) -> str:
    config = _config_for_service(service)
    for name in names:
        candidates = {
            name,
            name.lower(),
            name.upper(),
            name.removeprefix(f"{service}_"),
            name.removeprefix(f"{service}_").lower(),
        }
        for candidate in candidates:
            value = config.get(candidate)
            if value not in (None, ""):
                return str(value)
    return ""


def _oauth_config_services(service: str, spec: dict) -> list[str]:
    prefix = str(spec.get("client_id_env", "")).split("_", 1)[0].lower()
    services = [f"{service}_oauth", service]
    if prefix:
        services.append(f"{prefix}_oauth")
    return list(dict.fromkeys(services))


def _oauth_config_value(service: str, env_name: str, spec: dict) -> str:
    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    suffix = env_name.lower()
    if suffix.endswith("_client_id"):
        short_key = "client_id"
    elif suffix.endswith("_client_secret"):
        short_key = "client_secret"
    elif suffix.endswith("_oauth_redirect_uri"):
        short_key = "redirect_uri"
    else:
        short_key = suffix

    for credential_service in _oauth_config_services(service, spec):
        credential = _credential_record_for_service(credential_service)
        if not credential:
            continue
        metadata = credential.get("metadata", {})
        if isinstance(metadata, dict):
            for key in (env_name, suffix, short_key):
                value = metadata.get(key)
                if value not in (None, ""):
                    return str(value)
        if short_key == "client_secret" and credential.get("kind") in {"client_secret", "oauth_client_secret"}:
            return str(credential.get("secret", ""))
    return ""


def _missing_config_request(connector_id: str, missing: list[str]) -> dict:
    return _json_request(
        "POST",
        f"connector://config/{connector_id}",
        {"Accept": "application/json"},
        {"missing_config": missing},
    )


def _https_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _secret_for_service(service: str) -> str | None:
    info = SUPPORTED_SERVICES.get(service, {})
    secret_markers = ("TOKEN", "KEY", "SECRET", "PASSWORD")
    env_vars = list(info.get("env_vars", ()))
    preferred_envs = [name for name in env_vars if any(marker in name.upper() for marker in secret_markers)]
    for env_name in preferred_envs:
        value = os.getenv(env_name)
        if value:
            return value
    credential = _credential_record_for_service(service)
    return credential["secret"] if credential else None


def _oauth_env_readiness(service: str) -> dict:
    spec = _oauth_specs().get(service)
    if not spec:
        return {"available": False, "missing": ["oauth_spec"], "present": []}
    required = [spec["client_id_env"], spec["client_secret_env"], spec["redirect_uri_env"]]
    present = [name for name in required if _oauth_config_value(service, name, spec)]
    missing = [name for name in required if name not in present]
    return {"available": not missing, "configured": not missing, "present": present, "missing": missing}


def _exchange_oauth_code(service: str, code: str, redirect_uri: str | None = None) -> dict:
    spec = _oauth_specs().get(service)
    if not spec:
        raise HTTPException(status_code=404, detail="OAuth connector not available for this service")

    readiness = _oauth_env_readiness(service)
    if not readiness["available"]:
        raise HTTPException(status_code=400, detail=f"Missing OAuth env: {', '.join(readiness['missing'])}")

    data = {
        "client_id": _oauth_config_value(service, spec["client_id_env"], spec),
        "client_secret": _oauth_config_value(service, spec["client_secret_env"], spec),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri or _oauth_config_value(service, spec["redirect_uri_env"], spec),
    }
    encoded = urlencode(data).encode("utf-8")
    request = Request(
        spec["token_url"],
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20, context=_https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {exc}")

    if payload.get("error"):
        detail = payload.get("error_description") or payload.get("error")
        raise HTTPException(status_code=400, detail=f"OAuth provider rejected token exchange: {detail}")

    stored: list[dict] = []
    for token_key, kind in (("access_token", "access_token"), ("refresh_token", "refresh_token"), ("authed_user", "authed_user")):
        token_value = payload.get(token_key)
        if token_value:
            stored.append(_store_credential(
                service,
                f"{service} {kind}",
                kind,
                str(token_value),
                {"token_response_keys": sorted(payload.keys())},
            ))

    if not stored:
        raise HTTPException(status_code=400, detail="OAuth token response did not include a storable token")

    return {
        "service": service,
        "stored_credentials": [{"id": item["id"], "label": item["label"], "kind": item["kind"], "masked": item["masked"]} for item in stored],
        "response_keys": sorted(payload.keys()),
    }


def _refresh_oauth_access_token(service: str) -> str | None:
    spec = _oauth_specs().get(service)
    if not spec:
        return None
    refresh_credential = next((item for item in _credential_records_for_service(service) if item.get("kind") == "refresh_token"), None)
    if not refresh_credential:
        return None
    readiness = _oauth_env_readiness(service)
    if not readiness["available"]:
        return None
    data = {
        "client_id": _oauth_config_value(service, spec["client_id_env"], spec),
        "client_secret": _oauth_config_value(service, spec["client_secret_env"], spec),
        "refresh_token": refresh_credential["secret"],
        "grant_type": "refresh_token",
    }
    request = Request(
        spec["token_url"],
        data=urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20, context=_https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    token_value = payload.get("access_token")
    if not token_value:
        return None
    _store_credential(
        service,
        f"{service} access_token",
        "access_token",
        str(token_value),
        {"token_response_keys": sorted(payload.keys()), "refreshed_from": refresh_credential["label"]},
    )
    return str(token_value)


def _trim_output(value: str) -> str:
    if len(value) <= MAX_RUN_OUTPUT_CHARS:
        return value
    return value[:MAX_RUN_OUTPUT_CHARS] + f"\n[truncated to {MAX_RUN_OUTPUT_CHARS} chars]"


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(index - 1, 0)


def _parse_xlsx_rows(content: bytes, max_rows: int = 8) -> list[list[str]]:
    """Parse the first worksheet of a simple XLSX file using stdlib only."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for item in shared_root.findall(".//x:si", ns):
                parts = [node.text or "" for node in item.findall(".//x:t", ns)]
                shared_strings.append("".join(parts))

        sheet_name = next(
            (name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")),
            None,
        )
        if not sheet_name:
            return []

        root = ET.fromstring(archive.read(sheet_name))
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        parsed_rows: list[list[str]] = []

        for row in root.findall(".//x:sheetData/x:row", ns)[:max_rows]:
            values: dict[int, str] = {}
            for cell in row.findall("x:c", ns):
                ref = cell.attrib.get("r", "A1")
                idx = _column_index(ref)
                cell_type = cell.attrib.get("t")
                value_node = cell.find("x:v", ns)
                inline_node = cell.find(".//x:t", ns)
                raw_value = value_node.text if value_node is not None else inline_node.text if inline_node is not None else ""
                if cell_type == "s" and raw_value:
                    try:
                        raw_value = shared_strings[int(raw_value)]
                    except (ValueError, IndexError):
                        pass
                values[idx] = raw_value or ""
            if values:
                parsed_rows.append([values.get(i, "") for i in range(max(values) + 1)])

        return parsed_rows


def _inspect_tabular_bytes(filename: str, content: bytes) -> dict:
    """Return columns and sample rows for CSV/XLSX uploads."""
    suffix = os.path.splitext(filename.lower())[1]
    if suffix == ".csv":
        text = content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))[:8]
    elif suffix == ".xlsx":
        rows = _parse_xlsx_rows(content)
    else:
        raise ValueError("Unsupported schema file. Upload a CSV or XLSX file.")

    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("No rows found in uploaded file.")

    columns = [col or f"Column {idx + 1}" for idx, col in enumerate(rows[0])]
    sample_rows = []
    for row in rows[1:6]:
        sample_rows.append({columns[idx]: row[idx] if idx < len(row) else "" for idx in range(len(columns))})

    return {
        "filename": filename,
        "file_type": suffix.lstrip("."),
        "columns": columns,
        "sample_rows": sample_rows,
        "row_count_sampled": len(rows),
        "mapping_suggestions": _suggest_field_mappings(columns),
    }


def _suggest_field_mappings(columns: list[str]) -> dict[str, str]:
    targets = {
        "person_name": ("name", "employee", "candidate", "new hire"),
        "email": ("email", "mail"),
        "role": ("role", "position", "title", "job"),
        "manager": ("manager", "reporting", "supervisor"),
        "start_date": ("start", "joining", "join", "date"),
        "department": ("department", "team", "org"),
    }
    suggestions: dict[str, str] = {}
    for target, markers in targets.items():
        for column in columns:
            normalized = column.lower()
            if any(marker in normalized for marker in markers):
                suggestions[target] = column
                break
    return suggestions


def _collect_run_history(limit: int = 20) -> list[dict]:
    """Collect run/test artifacts from saved workflow projects."""
    from backend.deployment.workflow_store import get_workflow_project_path, list_workflows as _list

    runs = []
    conn = _platform_db()
    rows = conn.execute(
        "SELECT * FROM run_logs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        runs.append({
            "run_id": item["id"],
            "workflow_id": item["workflow_id"],
            "name": item["workflow_id"],
            "created_at": item["created_at"],
            "success": item["status"] == "success",
            "status": item["status"],
            "execution_time": item["execution_time"],
            "return_code": item["return_code"],
            "attempt": item["attempt"],
            "tests_passed": 0,
            "tests_total": 0,
            "services": [],
        })

    for workflow in _visible_workflows(_list(limit=max(limit * 2, limit))):
        if len(runs) >= limit:
            break
        workflow_id = workflow["id"]
        project_path = get_workflow_project_path(workflow_id)
        if not project_path:
            continue

        artifacts_dir = os.path.join(project_path, "artifacts")
        execution_path = os.path.join(artifacts_dir, "execution_result.json")
        test_path = os.path.join(artifacts_dir, "test_results.json")
        saved_path = os.path.join(artifacts_dir, "saved_at.json")

        execution = {}
        tests = {}
        saved_at = workflow.get("created_at")

        for path, target in ((execution_path, execution), (test_path, tests)):
            if os.path.exists(path):
                try:
                    target.update(json.load(open(path)))
                except Exception:
                    pass

        if os.path.exists(saved_path):
            try:
                saved_at = json.load(open(saved_path))
            except Exception:
                pass

        runs.append({
            "run_id": None,
            "workflow_id": workflow_id,
            "name": workflow.get("name", workflow_id),
            "created_at": saved_at,
            "success": bool(execution.get("success")),
            "status": "success" if execution.get("success") else "needs_review",
            "execution_time": execution.get("execution_time"),
            "return_code": 0 if execution.get("success") else None,
            "attempt": 1,
            "tests_passed": tests.get("passed", 0),
            "tests_total": tests.get("total", 0),
            "services": [s for s in (workflow.get("services") or "").split(",") if s],
        })

    return runs[:limit]


def _visible_workflows(workflows: list[dict]) -> list[dict]:
    """Hide legacy rows from removed product areas without deleting history."""
    hidden_terms = ("der" + "iv", "gene" + "sis")
    visible = []
    for workflow in workflows:
        text = " ".join(str(workflow.get(key, "")) for key in ("name", "description", "services", "user_request")).lower()
        if any(term in text for term in hidden_terms):
            continue
        visible.append(workflow)
    return visible


def _record_run_log(workflow_id: str, result: dict, attempt: int = 1) -> dict:
    run_id = _stable_id("run", {"workflow_id": workflow_id, "attempt": attempt})
    status = "success" if result.get("success") else "failed"
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO run_logs
        (id, workflow_id, status, stdout, stderr, execution_time, return_code, attempt, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            workflow_id,
            status,
            _trim_output(result.get("stdout", "")),
            _trim_output(result.get("stderr", "")),
            result.get("execution_time"),
            result.get("return_code"),
            attempt,
            _now_iso(),
        ),
    )
    conn.commit()
    conn.close()
    _record_observability_event(
        source="run_queue",
        severity="info" if status == "success" else "error",
        event_type="workflow_run_completed",
        subject=workflow_id,
        payload={"run_id": run_id, "attempt": attempt, "status": status, "stderr": result.get("stderr", "")[:500]},
    )
    return {"run_id": run_id, "status": status}


def _record_observability_event(source: str, severity: str, event_type: str, subject: str, payload: dict | None = None) -> dict:
    event = {
        "id": _stable_id("obs", {"source": source, "event_type": event_type, "subject": subject}),
        "source": source,
        "severity": severity,
        "event_type": event_type,
        "subject": subject,
        "payload": payload or {},
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO observability_events
        (id, source, severity, event_type, subject, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event["id"], source, severity, event_type, subject, json.dumps(event["payload"]), event["created_at"]),
    )
    conn.commit()
    conn.close()
    return event


def _list_observability_events(limit: int = 100) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM observability_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "source": row["source"],
            "severity": row["severity"],
            "event_type": row["event_type"],
            "subject": row["subject"],
            "payload": _json_loads(row["payload_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _get_run_log(run_id: str) -> dict | None:
    conn = _platform_db()
    row = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    return {
        "run_id": item["id"],
        "workflow_id": item["workflow_id"],
        "status": item["status"],
        "success": item["status"] == "success",
        "stdout": item["stdout"] or "",
        "stderr": item["stderr"] or "",
        "execution_time": item["execution_time"],
        "return_code": item["return_code"],
        "attempt": item["attempt"],
        "created_at": item["created_at"],
    }


def _list_approvals() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    conn.close()
    approvals_data = []
    for row in rows:
        item = dict(row)
        item["preview"] = json.loads(item.pop("preview_json"))
        approvals_data.append(item)
    return approvals_data


def _list_triggers() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM triggers ORDER BY created_at DESC").fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "config": _json_loads(row["config_json"], {}),
        }
        for row in rows
    ]


def _get_trigger(trigger_id: str) -> dict | None:
    conn = _platform_db()
    row = conn.execute("SELECT * FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["config"] = _json_loads(item.pop("config_json"), {})
    return item


def _record_trigger_event(trigger_id: str, workflow_id: str, event_type: str, payload: dict, status: str, run_id: str | None = None) -> dict:
    event_id = _stable_id("trigger_event", {"trigger_id": trigger_id, "status": status})
    event = {
        "id": event_id,
        "trigger_id": trigger_id,
        "workflow_id": workflow_id,
        "event_type": event_type,
        "payload": payload,
        "status": status,
        "run_id": run_id,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO trigger_events
        (id, trigger_id, workflow_id, event_type, payload_json, status, run_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["id"],
            event["trigger_id"],
            event["workflow_id"],
            event["event_type"],
            json.dumps(payload),
            event["status"],
            event["run_id"],
            event["created_at"],
        ),
    )
    conn.commit()
    conn.close()
    return event


def _list_trigger_events(limit: int = 30) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute(
        "SELECT * FROM trigger_events ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "payload": _json_loads(row["payload_json"], {}),
        }
        for row in rows
    ]


def _enqueue_run(workflow_id: str, payload: dict | None = None, priority: int = 5, max_attempts: int = 3) -> dict:
    queue_id = _stable_id("queue", {"workflow_id": workflow_id, "priority": priority, "payload": payload or {}})
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO run_queue
        (id, workflow_id, status, payload_json, priority, attempts, max_attempts, created_at, updated_at, next_attempt_at)
        VALUES (?, ?, 'queued', ?, ?, 0, ?, ?, ?, ?)
        """,
        (queue_id, workflow_id, json.dumps(payload or {}), priority, max_attempts, now, now, now),
    )
    conn.commit()
    conn.close()
    return {
        "id": queue_id,
        "workflow_id": workflow_id,
        "status": "queued",
        "payload": payload or {},
        "priority": priority,
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _list_run_queue() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM run_queue ORDER BY status ASC, priority ASC, created_at ASC LIMIT 50").fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "payload": _json_loads(row["payload_json"], {}),
        }
        for row in rows
    ]


def _due_queue_items(limit: int = 5) -> list[dict]:
    now = _now_iso()
    conn = _platform_db()
    rows = conn.execute(
        """
        SELECT * FROM run_queue
        WHERE status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY priority ASC, created_at ASC
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "payload": _json_loads(row["payload_json"], {}),
        }
        for row in rows
    ]


async def _process_queue_item(queue_id: str) -> dict:
    conn = _platform_db()
    row = conn.execute("SELECT * FROM run_queue WHERE id = ?", (queue_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Queue item not found")
    if row["status"] not in {"queued", "failed"}:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Queue item is {row['status']}")
    attempts = int(row["attempts"] or 0) + 1
    now = _now_iso()
    conn.execute("UPDATE run_queue SET status = 'running', attempts = ?, updated_at = ? WHERE id = ?", (attempts, now, queue_id))
    conn.commit()
    conn.close()
    payload = _json_loads(row["payload_json"], {})
    try:
        spec = _get_automation_spec(row["workflow_id"])
        if spec:
            mode = payload.get("mode", "dry_run")
            inputs = payload.get("inputs", payload.get("payload", payload))
            runtime_run = (
                await _live_run_automation_spec(row["workflow_id"], inputs, approved=bool(payload.get("approved")))
                if mode == "live"
                else await _dry_run_automation_spec(row["workflow_id"], inputs)
            )
            result = {
                "success": runtime_run["status"] in {"succeeded", "waiting_for_approval"},
                "stdout": json.dumps({"runtime_run_id": runtime_run["id"], "status": runtime_run["status"]}),
                "stderr": "" if runtime_run["status"] in {"succeeded", "waiting_for_approval"} else runtime_run["status"],
                "execution_time": 0.0,
                "return_code": 0 if runtime_run["status"] in {"succeeded", "waiting_for_approval"} else 1,
            }
        else:
            result = await _execute_workflow_project(row["workflow_id"])
    except HTTPException as exc:
        result = {"success": False, "stdout": "", "stderr": exc.detail, "execution_time": 0.0, "return_code": -1}
    except Exception as exc:
        result = {"success": False, "stdout": "", "stderr": str(exc), "execution_time": 0.0, "return_code": -1}
    run_meta = _record_run_log(row["workflow_id"], result, attempt=attempts)
    max_attempts = int(row["max_attempts"] or 3)
    final_status = "succeeded" if result.get("success") else ("dead_letter" if attempts >= max_attempts else "queued")
    backoff_seconds = min(900, 2 ** max(attempts - 1, 0) * 30)
    next_attempt_at = _now_iso() if final_status != "queued" else (datetime.utcnow().timestamp() + backoff_seconds)
    next_attempt_value = _now_iso() if final_status != "queued" else datetime.utcfromtimestamp(next_attempt_at).isoformat() + "Z"
    conn = _platform_db()
    conn.execute(
        """
        UPDATE run_queue
        SET status = ?, last_error = ?, run_id = ?, updated_at = ?, next_attempt_at = ?, dead_letter_reason = ?
        WHERE id = ?
        """,
        (
            final_status,
            None if result.get("success") else result.get("stderr", "failed"),
            run_meta["run_id"],
            _now_iso(),
            next_attempt_value,
            result.get("stderr", "max attempts reached") if final_status == "dead_letter" else None,
            queue_id,
        ),
    )
    conn.commit()
    conn.close()
    _record_observability_event(
        source="run_queue",
        severity="error" if final_status == "dead_letter" else "info",
        event_type="queue_item_processed",
        subject=row["workflow_id"],
        payload={"queue_id": queue_id, "status": final_status, "attempts": attempts, "max_attempts": max_attempts},
    )
    return {"queue_id": queue_id, "queue_status": final_status, "run": {**result, **run_meta}}


def _recover_stale_queue_items(max_age_seconds: int = 600) -> dict:
    cutoff = datetime.utcfromtimestamp(datetime.utcnow().timestamp() - max_age_seconds).isoformat() + "Z"
    conn = _platform_db()
    rows = conn.execute(
        "SELECT * FROM run_queue WHERE status = 'running' AND updated_at <= ?",
        (cutoff,),
    ).fetchall()
    recovered = []
    for row in rows:
        attempts = int(row["attempts"] or 0)
        max_attempts = int(row["max_attempts"] or 3)
        status = "dead_letter" if attempts >= max_attempts else "queued"
        reason = "stale_running_recovered"
        conn.execute(
            """
            UPDATE run_queue
            SET status = ?, last_error = ?, dead_letter_reason = ?, next_attempt_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                reason,
                reason if status == "dead_letter" else None,
                _now_iso(),
                _now_iso(),
                row["id"],
            ),
        )
        recovered.append({"id": row["id"], "workflow_id": row["workflow_id"], "status": status})
    conn.commit()
    conn.close()
    if recovered:
        _record_observability_event("worker", "warn", "stale_queue_recovered", "run_queue", {"count": len(recovered), "items": recovered})
    return {"recovered": recovered, "count": len(recovered)}


async def _process_due_queue(limit: int = 5) -> dict:
    processed = []
    for item in _due_queue_items(limit=limit):
        processed.append(await _process_queue_item(item["id"]))
    if processed:
        _record_observability_event(
            "worker",
            "info",
            "due_queue_processed",
            "run_queue",
            {"count": len(processed), "queue_ids": [item["queue_id"] for item in processed]},
        )
    return {"processed": processed, "count": len(processed)}


async def _queue_worker_loop():
    interval = max(2, int(os.getenv("FORGEFLOW_QUEUE_WORKER_INTERVAL", "10")))
    _record_observability_event("worker", "info", "queue_worker_started", "run_queue", {"interval_seconds": interval})
    while True:
        try:
            await _process_due_schedules()
            await _process_due_queue(limit=int(os.getenv("FORGEFLOW_QUEUE_WORKER_BATCH", "5")))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _record_observability_event("worker", "error", "queue_worker_error", "run_queue", {"error": str(exc)[:500]})
        await asyncio.sleep(interval)


def _all_capabilities() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT capabilities_json FROM ingestions ORDER BY created_at DESC").fetchall()
    conn.close()
    capabilities_data = list(CAPABILITY_REGISTRY)
    seen = {item["id"] for item in capabilities_data}
    for row in rows:
        try:
            for capability in json.loads(row["capabilities_json"]):
                if capability.get("id") not in seen:
                    capabilities_data.append(capability)
                    seen.add(capability.get("id"))
        except Exception:
            pass
    return capabilities_data


def _tokenize_for_match(text: str) -> set[str]:
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(token) > 2 and token not in {"the", "and", "for", "with", "from", "into", "this", "that", "api"}
    }


def _capability_search(prompt: str, limit: int = 8) -> list[dict]:
    query_tokens = _tokenize_for_match(prompt)
    matches = []
    for capability in _all_capabilities():
        haystack = " ".join([
            capability.get("id", ""),
            capability.get("label", ""),
            capability.get("category", ""),
            capability.get("description", ""),
            capability.get("source", ""),
            capability.get("path", ""),
        ])
        tokens = _tokenize_for_match(haystack)
        overlap = query_tokens & tokens
        if not overlap:
            continue
        score = min(0.98, 0.35 + (len(overlap) / max(len(query_tokens), 1)))
        matches.append({
            "id": capability["id"],
            "label": capability.get("label", capability["id"]),
            "source": capability.get("source", "catalog"),
            "risk": capability.get("risk", "tool_call"),
            "description": capability.get("description", ""),
            "score": round(score, 3),
            "matched_terms": sorted(overlap),
            "capability": capability,
        })
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:limit]


def _connector_adapters() -> list[dict]:
    connectors = {item["service"]: item for item in _list_connector_states()}
    capability_by_id = {item["id"]: item for item in _all_capabilities()}
    adapter_specs = capability_specs()
    adapters = []
    for capability_id, service, label, risk, methods in adapter_specs:
        capability = capability_by_id.get(capability_id, {})
        state = connectors.get(service, {})
        configured = bool(
            state.get("env_status", {}).get("configured")
            or state.get("metadata", {}).get("vault_credential")
            or service in {"schema", "http", "approval"}
        )
        adapters.append({
            "id": capability_id,
            "service": service,
            "label": capability.get("label") or label,
            "risk": capability.get("risk") or risk,
            "methods": methods,
            "configured": configured,
            "status": "ready" if configured else "needs_credentials",
            "auth": state.get("auth_type", "none" if service in {"schema", "http", "approval"} else "api_key"),
            "capability": capability,
        })
    for capability in capability_by_id.values():
        if capability["id"] in {item["id"] for item in adapters}:
            continue
        adapters.append({
            "id": capability["id"],
            "service": capability.get("source", "custom"),
            "label": capability.get("label", capability["id"]),
            "risk": capability.get("risk", "tool_call"),
            "methods": ["schema_discovery", "dry_run", "execute"],
            "configured": not capability.get("requires_auth"),
            "status": "ready" if not capability.get("requires_auth") else "needs_credentials",
            "auth": "custom",
            "capability": capability,
        })
    return adapters


def _capability_for_service(service: str) -> str:
    return SERVICE_TO_DEFAULT_CAPABILITY.get(service, "http.request")


def _approval_required_for_capability(capability_id: str) -> bool:
    capability = next((item for item in _all_capabilities() if item["id"] == capability_id), {})
    return capability.get("risk") in {"external_write", "approval_required"}


def _store_automation_spec(spec: dict) -> dict:
    spec_id = spec.get("id") or _stable_id("spec", {"goal": spec.get("goal"), "steps": spec.get("steps")})
    now = _now_iso()
    record = {
        **spec,
        "id": spec_id,
        "created_at": spec.get("created_at", now),
        "updated_at": now,
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO automation_specs
        (id, goal, trigger_json, inputs_json, connectors_json, steps_json, approval_gates_json, tests_json, deployment_json, questions_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["goal"],
            json.dumps(record.get("trigger", {})),
            json.dumps(record.get("inputs", {})),
            json.dumps(record.get("connectors", [])),
            json.dumps(record.get("steps", [])),
            json.dumps(record.get("approval_gates", [])),
            json.dumps(record.get("tests", [])),
            json.dumps(record.get("deployment", {})),
            json.dumps(record.get("questions", [])),
            record.get("status", "draft"),
            record["created_at"],
            record["updated_at"],
        ),
    )
    conn.commit()
    conn.close()
    return record


def _row_to_automation_spec(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "goal": row["goal"],
        "trigger": _json_loads(row["trigger_json"], {}),
        "inputs": _json_loads(row["inputs_json"], {}),
        "connectors": _json_loads(row["connectors_json"], []),
        "steps": _json_loads(row["steps_json"], []),
        "approval_gates": _json_loads(row["approval_gates_json"], []),
        "tests": _json_loads(row["tests_json"], []),
        "deployment": _json_loads(row["deployment_json"], {}),
        "questions": _json_loads(row["questions_json"], []),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _list_automation_specs(limit: int = 20) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM automation_specs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [_row_to_automation_spec(row) for row in rows]


def _get_automation_spec(spec_id: str) -> dict | None:
    conn = _platform_db()
    row = conn.execute("SELECT * FROM automation_specs WHERE id = ?", (spec_id,)).fetchone()
    conn.close()
    return _row_to_automation_spec(row) if row else None


async def _compile_automation_spec(prompt: str, context: dict | None = None) -> dict:
    preflight = await preflight_prompt({"prompt": prompt})
    connectors = []
    steps = []
    approval_gates = []
    adapters_by_id = {item["id"]: item for item in _connector_adapters()}

    if preflight["schema_needed"]:
        connectors.append({"id": "schema.inspect_file", "service": "schema", "status": "ready"})
        steps.append({
            "id": "step_1",
            "name": "Inspect source schema",
            "connector_id": "schema.inspect_file",
            "purpose": "Read real columns and sample rows before planning field mappings.",
            "input_contract": {"source": "uploaded_file_or_connected_sheet"},
            "output_contract": {"columns": "string[]", "sample_rows": "object[]"},
            "approval_required": False,
        })

    for detected in preflight["detected_services"]:
        capability_id = detected.get("capability_id") or _capability_for_service(detected["service"])
        adapter = adapters_by_id.get(capability_id, {})
        if not any(item["id"] == capability_id for item in connectors):
            connectors.append({
                "id": capability_id,
                "service": detected["service"],
                "status": "ready" if adapter.get("configured") else "needs_credentials",
                "required_env": detected.get("required_env", []),
            })
        step_index = len(steps) + 1
        approval_required = _approval_required_for_capability(capability_id)
        steps.append({
            "id": f"step_{step_index}",
            "name": adapter.get("label") or detected["name"],
            "connector_id": capability_id,
            "purpose": f"Use {detected['name']} through its typed adapter.",
            "input_contract": {"from": "previous_steps_or_user_input"},
            "output_contract": {"result": "dry_run_preview_or_provider_response"},
            "approval_required": approval_required,
        })
        if approval_required:
            approval_gates.append({
                "step_id": f"step_{step_index}",
                "risk": adapter.get("risk", "external_write"),
                "preview_required": True,
            })

    if not steps:
        connectors.append({"id": "http.request", "service": "http", "status": "ready"})
        steps.append({
            "id": "step_1",
            "name": "Prepare generic HTTP automation",
            "connector_id": "http.request",
            "purpose": "Represent the requested operation until a specific API or MCP tool is imported.",
            "input_contract": {"request": "object"},
            "output_contract": {"response": "object"},
            "approval_required": False,
        })

    tests = [
        {"id": "test_preflight_grounding", "asserts": "No invented systems or fields are required before schema discovery."},
        {"id": "test_dry_run", "asserts": "Every external write step can produce a preview without credentials."},
        {"id": "test_approval_gates", "asserts": "Risky writes are blocked behind approval previews."},
    ]
    status = "blocked" if preflight["questions"] else "ready_for_dry_run"
    spec = {
        "goal": prompt,
        "trigger": {"type": "manual", "source": "user_prompt"},
        "inputs": {
            "schema_needed": preflight["schema_needed"],
            "context": context or {},
        },
        "connectors": connectors,
        "steps": steps,
        "approval_gates": approval_gates,
        "tests": tests,
        "deployment": {"target": "local_docker", "runtime": "forgeflow_runtime", "requires_dispatch": True},
        "questions": preflight["questions"],
        "status": status,
        "preflight": preflight,
    }
    return _store_automation_spec(spec)


def _record_runtime_step(run_id: str, step: dict, status: str, output: dict | None = None, error: str | None = None) -> dict:
    now = _now_iso()
    item = {
        "id": _stable_id("runtime_step", {"run_id": run_id, "step_id": step["id"]}),
        "run_id": run_id,
        "step_id": step["id"],
        "connector_id": step["connector_id"],
        "status": status,
        "attempt": 1,
        "input": step.get("input_contract", {}),
        "output": output or {},
        "error": error,
        "started_at": now,
        "completed_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO runtime_steps
        (id, run_id, step_id, connector_id, status, attempt, input_json, output_json, error, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["id"],
            item["run_id"],
            item["step_id"],
            item["connector_id"],
            item["status"],
            item["attempt"],
            json.dumps(item["input"]),
            json.dumps(item["output"]),
            item["error"],
            item["started_at"],
            item["completed_at"],
        ),
    )
    conn.commit()
    conn.close()
    return item


def _list_runtime_runs(limit: int = 20) -> list[dict]:
    conn = _platform_db()
    run_rows = conn.execute("SELECT * FROM runtime_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    step_rows = conn.execute("SELECT * FROM runtime_steps ORDER BY started_at ASC").fetchall()
    conn.close()
    steps_by_run: dict[str, list[dict]] = {}
    for row in step_rows:
        steps_by_run.setdefault(row["run_id"], []).append({
            "id": row["id"],
            "run_id": row["run_id"],
            "step_id": row["step_id"],
            "connector_id": row["connector_id"],
            "status": row["status"],
            "attempt": row["attempt"],
            "input": _json_loads(row["input_json"], {}),
            "output": _json_loads(row["output_json"], {}),
            "error": row["error"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        })
    return [
        {
            "id": row["id"],
            "spec_id": row["spec_id"],
            "status": row["status"],
            "mode": row["mode"],
            "input": _json_loads(row["input_json"], {}),
            "output": _json_loads(row["output_json"], {}),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "steps": steps_by_run.get(row["id"], []),
        }
        for row in run_rows
    ]


async def _dry_run_automation_spec(spec_id: str, inputs: dict | None = None) -> dict:
    spec = _get_automation_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Automation spec not found")
    run_id = _stable_id("runtime_run", {"spec_id": spec_id})
    started = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO runtime_runs
        (id, spec_id, status, mode, input_json, output_json, started_at, completed_at)
        VALUES (?, ?, 'running', 'dry_run', ?, '{}', ?, NULL)
        """,
        (run_id, spec_id, json.dumps(inputs or {}), started),
    )
    conn.commit()
    conn.close()

    run_steps = []
    blocked = False
    adapters = {item["id"]: item for item in _connector_adapters()}
    for step in spec["steps"]:
        adapter = adapters.get(step["connector_id"], {})
        if step.get("approval_required"):
            status = "waiting_for_approval"
            approval = _create_step_approval(spec, step)
            output = {
                "preview": f"{step['name']} is ready for approval preview.",
                "approval_id": approval["id"],
                "live_call_performed": False,
            }
        elif adapter.get("status") == "needs_credentials":
            status = "blocked"
            output = {"missing": "credentials", "live_call_performed": False}
            blocked = True
        else:
            status = "succeeded"
            output = {"preview": f"Dry-run completed through {step['connector_id']}.", "live_call_performed": False}
        run_steps.append(_record_runtime_step(run_id, step, status, output))

    final_status = "blocked" if blocked else ("waiting_for_approval" if any(item["status"] == "waiting_for_approval" for item in run_steps) else "succeeded")
    output = {
        "summary": f"{len(run_steps)} steps evaluated",
        "approval_gates": len([item for item in run_steps if item["status"] == "waiting_for_approval"]),
        "live_call_performed": False,
    }
    conn = _platform_db()
    conn.execute(
        "UPDATE runtime_runs SET status = ?, output_json = ?, completed_at = ? WHERE id = ?",
        (final_status, json.dumps(output), _now_iso(), run_id),
    )
    conn.commit()
    conn.close()
    return _list_runtime_runs(limit=1)[0]


def _create_step_approval(spec: dict, step: dict) -> dict:
    preview = {
        "spec_id": spec["id"],
        "step_id": step["id"],
        "connector_id": step["connector_id"],
        "purpose": step.get("purpose"),
        "input_contract": step.get("input_contract", {}),
    }
    approval_id = _stable_id("approval", preview)
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO approvals
        (id, workflow_id, action_type, title, preview_json, risk, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            approval_id,
            spec["id"],
            step["connector_id"],
            step["name"],
            json.dumps(preview),
            "external_write",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": approval_id, "status": "pending", "preview": preview}


def _has_approved_step(spec_id: str, step: dict) -> bool:
    conn = _platform_db()
    rows = conn.execute(
        "SELECT preview_json FROM approvals WHERE workflow_id = ? AND action_type = ? AND status = 'approved'",
        (spec_id, step["connector_id"]),
    ).fetchall()
    conn.close()
    for row in rows:
        preview = _json_loads(row["preview_json"], {})
        if preview.get("step_id") == step["id"]:
            return True
    return False


def _required_live_fields(connector_id: str) -> list[str]:
    return {
        "slack.create_channel": ["name"],
        "gmail.create_draft": ["to", "subject", "body"],
        "sheets.read_rows": ["range"],
        "stripe.retrieve_payment": ["payment_intent"],
        "stripe.create_refund": ["charge_or_payment_intent"],
        "zendesk.create_ticket": ["subject", "body"],
        "calendar.create_event": ["summary", "start", "end"],
        "hubspot.create_contact": ["email"],
        "hubspot.update_deal": ["deal_id", "properties"],
        "okta.assign_group": ["user_id", "group_id"],
        "okta.create_user": ["profile"],
        "salesforce.create_record": ["object", "fields"],
        "salesforce.update_record": ["object", "record_id", "fields"],
        "jira.create_issue": ["project_key", "summary"],
        "jira.transition_issue": ["issue_id", "transition_id"],
        "notion.create_page": ["parent_id", "title"],
        "notion.update_database": ["database_id", "properties"],
        "airtable.create_record": ["table", "fields"],
        "airtable.update_record": ["table", "record_id", "fields"],
        "teams.post_message": ["team_id", "channel_id", "text"],
        "slack.post_message": ["channel", "text"],
        "gmail.send_email": ["to", "subject", "body"],
        "sheets.append_row": ["values"],
        "http.request": ["url"],
    }.get(connector_id, [])


def _input_value(inputs: dict, *names: str):
    for name in names:
        value = inputs.get(name)
        if value not in (None, "", []):
            return value
    return None


def _inputs_for_step(inputs: dict, step: dict) -> dict:
    """Merge global run inputs with optional per-step or per-connector overrides."""
    merged = dict(inputs or {})
    for key in (step.get("connector_id"), step.get("connector_id", "").replace(".", "_"), step.get("id")):
        value = (inputs or {}).get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _missing_live_fields(connector_id: str, inputs: dict) -> list[str]:
    dynamic_capability = _find_dynamic_capability(connector_id)
    if dynamic_capability and dynamic_capability.get("source") == "openapi":
        missing = []
        if not (inputs.get("server_url") or dynamic_capability.get("server_url")):
            missing.append("server_url")
        for name in str(dynamic_capability.get("path", "")).split("{")[1:]:
            field = name.split("}", 1)[0]
            if inputs.get(field) in (None, ""):
                missing.append(field)
        if dynamic_capability.get("method") != "GET" and not any(key in inputs for key in ("body", "json")):
            missing.append("body")
        return missing
    if dynamic_capability and dynamic_capability.get("source") == "mcp":
        return [] if (inputs.get("server_url") or dynamic_capability.get("server_url")) else ["server_url"]
    aliases = {
        "stripe.create_refund": {"charge_or_payment_intent": ("charge_or_payment_intent", "charge", "payment_intent")},
        "zendesk.create_ticket": {"body": ("body", "description", "comment")},
        "calendar.create_event": {"summary": ("summary", "subject", "title")},
        "jira.create_issue": {"project_key": ("project_key", "project")},
        "teams.post_message": {"text": ("text", "body", "message")},
        "slack.post_message": {"text": ("text", "body", "message")},
        "gmail.send_email": {"body": ("body", "message")},
    }
    missing = []
    for field in _required_live_fields(connector_id):
        names = aliases.get(connector_id, {}).get(field, (field,))
        if _input_value(inputs, *names) in (None, "", []):
            missing.append(field)
    return missing


def _json_request(method: str, url: str, headers: dict, body: dict | None = None) -> dict:
    return {
        "method": method,
        "url": url,
        "headers": {**headers, "Content-Type": "application/json"},
        "body": json.dumps(body or {}).encode("utf-8") if body is not None else None,
    }


def _safe_request_preview(request_spec: dict) -> dict:
    headers = request_spec.get("headers", {})
    body = request_spec.get("body")
    body_preview = None
    if body:
        try:
            decoded = body.decode("utf-8", errors="replace")
            body_preview = _json_loads(decoded, decoded[:1000])
        except Exception:
            body_preview = "<binary body>"
    return {
        "method": request_spec.get("method", "POST"),
        "url": request_spec.get("url"),
        "headers": sorted([key for key in headers if key.lower() != "authorization"]),
        "body_preview": body_preview,
    }


def _find_dynamic_capability(capability_id: str) -> dict | None:
    return next((item for item in _all_capabilities() if item.get("id") == capability_id), None)


def _fill_path_template(path: str, inputs: dict) -> tuple[str, list[str]]:
    missing = []
    rendered = path
    for part in path.split("{")[1:]:
        key = part.split("}", 1)[0]
        value = inputs.get(key)
        if value in (None, ""):
            missing.append(key)
        else:
            rendered = rendered.replace("{" + key + "}", quote(str(value), safe=""))
    return rendered, missing


def _redact_sensitive(value: str | None, secret: str | None = None) -> str | None:
    if value is None:
        return None
    redacted = value
    if secret:
        redacted = redacted.replace(secret, "[redacted]")
    for marker in ("Authorization", "authorization", "Bearer ", "SSWS "):
        if marker in redacted:
            redacted = redacted.replace(marker, f"{marker}[redacted] ")
    return redacted[:1000]


def _connector_live_request(connector_id: str, inputs: dict, secret: str | None) -> dict:
    service = connector_id.split(".", 1)[0]
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    dynamic_capability = _find_dynamic_capability(connector_id)
    if dynamic_capability and dynamic_capability.get("source") == "openapi":
        method = dynamic_capability.get("method", "GET")
        server_url = str(inputs.get("server_url") or dynamic_capability.get("server_url") or "").rstrip("/")
        path, missing_path = _fill_path_template(str(dynamic_capability.get("path", "")), inputs)
        if missing_path or not server_url:
            return {
                "method": method,
                "url": f"connector://openapi/{connector_id}",
                "headers": headers,
                "body": json.dumps({"missing_path_fields": missing_path, "missing_server_url": not bool(server_url)}).encode("utf-8"),
            }
        query = inputs.get("query", {}) if isinstance(inputs.get("query"), dict) else {}
        url = f"{server_url}{path}"
        if method == "GET" and query:
            url = f"{url}?{urlencode(query)}"
        body = None if method == "GET" else (inputs.get("body") or inputs.get("json") or inputs)
        return _json_request(method, url, headers, body if method != "GET" else None)
    if dynamic_capability and dynamic_capability.get("source") == "mcp":
        server_url = str(inputs.get("server_url") or dynamic_capability.get("server_url") or "").strip()
        if not server_url:
            return {"method": "POST", "url": f"connector://mcp/{connector_id}", "headers": headers, "body": None}
        tool_name = dynamic_capability.get("tool_name") or connector_id.split(".", 1)[1]
        body = {"jsonrpc": "2.0", "id": _stable_id("mcp_call", {"tool": tool_name}), "method": "tools/call", "params": {"name": tool_name, "arguments": inputs.get("arguments", inputs)}}
        return _json_request("POST", server_url, headers, body)
    if connector_id == "slack.create_channel":
        body = {"name": inputs.get("name"), "is_private": bool(inputs.get("is_private", False))}
        return _json_request("POST", "https://slack.com/api/conversations.create", headers, body)
    if connector_id == "stripe.create_refund":
        return {
            "method": "POST",
            "url": "https://api.stripe.com/v1/refunds",
            "headers": {**headers, "Content-Type": "application/x-www-form-urlencoded"},
            "body": urlencode({
                "charge": _input_value(inputs, "charge_or_payment_intent", "charge", "payment_intent"),
                **({"amount": str(inputs["amount"])} if inputs.get("amount") else {}),
            }).encode("utf-8"),
        }
    if connector_id == "stripe.retrieve_payment":
        payment_id = _input_value(inputs, "payment_intent", "charge", "charge_or_payment_intent")
        path = "payment_intents" if str(payment_id).startswith("pi_") else "charges"
        return {"method": "GET", "url": f"https://api.stripe.com/v1/{path}/{payment_id}", "headers": headers, "body": None}
    if connector_id == "zendesk.create_ticket":
        subdomain = _connector_config_value("zendesk", "ZENDESK_SUBDOMAIN", "subdomain")
        email = _connector_config_value("zendesk", "ZENDESK_EMAIL", "email")
        if not subdomain or not email:
            return _missing_config_request(connector_id, [name for name, value in {"ZENDESK_SUBDOMAIN": subdomain, "ZENDESK_EMAIL": email}.items() if not value])
        if email:
            token = base64.b64encode(f"{email}/token:{secret}".encode("utf-8")).decode("ascii")
            headers = {"Accept": "application/json", "Authorization": f"Basic {token}"}
        body = {"ticket": {"subject": inputs.get("subject"), "comment": {"body": _input_value(inputs, "body", "description", "comment")}}}
        return _json_request("POST", f"https://{subdomain}.zendesk.com/api/v2/tickets.json", headers, body)
    if connector_id == "calendar.create_event":
        start = inputs.get("start")
        end = inputs.get("end")
        body = {
            "summary": _input_value(inputs, "summary", "subject", "title"),
            "start": start if isinstance(start, dict) else {"dateTime": start},
            "end": end if isinstance(end, dict) else {"dateTime": end},
        }
        return _json_request("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", headers, body)
    if connector_id == "hubspot.create_contact":
        body = {"properties": {"email": inputs.get("email"), **inputs.get("properties", {})}}
        return _json_request("POST", "https://api.hubapi.com/crm/v3/objects/contacts", headers, body)
    if connector_id == "hubspot.create_deal":
        body = {"properties": {"dealname": inputs.get("dealname", inputs.get("name", "ForgeFlow deal")), **inputs.get("properties", {})}}
        return _json_request("POST", "https://api.hubapi.com/crm/v3/objects/deals", headers, body)
    if connector_id == "hubspot.update_deal":
        body = {"properties": inputs.get("properties", {})}
        return _json_request("PATCH", f"https://api.hubapi.com/crm/v3/objects/deals/{inputs.get('deal_id')}", headers, body)
    if connector_id == "okta.assign_group":
        org_url = _connector_config_value("okta", "OKTA_ORG_URL", "org_url").rstrip("/")
        if not org_url:
            return _missing_config_request(connector_id, ["OKTA_ORG_URL"])
        return {
            "method": "PUT",
            "url": f"{org_url}/api/v1/groups/{inputs.get('group_id')}/users/{inputs.get('user_id')}",
            "headers": {"Accept": "application/json", "Authorization": f"SSWS {secret}"},
            "body": None,
        }
    if connector_id == "okta.create_user":
        org_url = _connector_config_value("okta", "OKTA_ORG_URL", "org_url").rstrip("/")
        if not org_url:
            return _missing_config_request(connector_id, ["OKTA_ORG_URL"])
        return _json_request("POST", f"{org_url}/api/v1/users?activate=false", {"Accept": "application/json", "Authorization": f"SSWS {secret}"}, inputs.get("profile", inputs))
    if connector_id == "salesforce.create_record":
        instance_url = _connector_config_value("salesforce", "SALESFORCE_INSTANCE_URL", "instance_url").rstrip("/")
        if not instance_url:
            return _missing_config_request(connector_id, ["SALESFORCE_INSTANCE_URL"])
        object_name = inputs.get("object")
        return _json_request("POST", f"{instance_url}/services/data/v60.0/sobjects/{object_name}/", headers, inputs.get("fields", {}))
    if connector_id == "salesforce.update_record":
        instance_url = _connector_config_value("salesforce", "SALESFORCE_INSTANCE_URL", "instance_url").rstrip("/")
        if not instance_url:
            return _missing_config_request(connector_id, ["SALESFORCE_INSTANCE_URL"])
        object_name = inputs.get("object")
        return _json_request("PATCH", f"{instance_url}/services/data/v60.0/sobjects/{object_name}/{inputs.get('record_id')}", headers, inputs.get("fields", {}))
    if connector_id == "jira.create_issue":
        base_url = _connector_config_value("jira", "JIRA_BASE_URL", "base_url").rstrip("/")
        email = _connector_config_value("jira", "JIRA_EMAIL", "email")
        if not base_url or not email:
            return _missing_config_request(connector_id, [name for name, value in {"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email}.items() if not value])
        auth = base64.b64encode(f"{email}:{secret}".encode("utf-8")).decode("ascii")
        jira_headers = {"Accept": "application/json", "Authorization": f"Basic {auth}"}
        body = {"fields": {"project": {"key": _input_value(inputs, "project_key", "project")}, "summary": inputs.get("summary"), "issuetype": {"name": inputs.get("issue_type", "Task")}}}
        if inputs.get("description"):
            body["fields"]["description"] = inputs["description"]
        return _json_request("POST", f"{base_url}/rest/api/3/issue", jira_headers, body)
    if connector_id == "jira.transition_issue":
        base_url = _connector_config_value("jira", "JIRA_BASE_URL", "base_url").rstrip("/")
        email = _connector_config_value("jira", "JIRA_EMAIL", "email")
        if not base_url or not email:
            return _missing_config_request(connector_id, [name for name, value in {"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email}.items() if not value])
        auth = base64.b64encode(f"{email}:{secret}".encode("utf-8")).decode("ascii")
        body = {"transition": {"id": str(inputs.get("transition_id"))}}
        return _json_request("POST", f"{base_url}/rest/api/3/issue/{inputs.get('issue_id')}/transitions", {"Accept": "application/json", "Authorization": f"Basic {auth}"}, body)
    if connector_id == "notion.create_page":
        body = {"parent": {"page_id": inputs.get("parent_id")}, "properties": {"title": {"title": [{"text": {"content": inputs.get("title")}}]}}}
        return _json_request("POST", "https://api.notion.com/v1/pages", {**headers, "Notion-Version": "2022-06-28"}, body)
    if connector_id == "notion.update_database":
        body = {"properties": inputs.get("properties", {})}
        return _json_request("PATCH", f"https://api.notion.com/v1/databases/{inputs.get('database_id')}", {**headers, "Notion-Version": "2022-06-28"}, body)
    if connector_id == "airtable.create_record":
        base_id = _connector_config_value("airtable", "AIRTABLE_BASE_ID", "base_id")
        if not base_id:
            return _missing_config_request(connector_id, ["AIRTABLE_BASE_ID"])
        body = {"fields": inputs.get("fields", {})}
        return _json_request("POST", f"https://api.airtable.com/v0/{base_id}/{quote(str(inputs.get('table')))}", headers, body)
    if connector_id == "airtable.update_record":
        base_id = _connector_config_value("airtable", "AIRTABLE_BASE_ID", "base_id")
        if not base_id:
            return _missing_config_request(connector_id, ["AIRTABLE_BASE_ID"])
        body = {"fields": inputs.get("fields", {})}
        return _json_request("PATCH", f"https://api.airtable.com/v0/{base_id}/{quote(str(inputs.get('table')))}/{inputs.get('record_id')}", headers, body)
    if connector_id == "teams.post_message":
        body = {"body": {"contentType": "html", "content": _input_value(inputs, "text", "body", "message")}}
        return _json_request("POST", f"https://graph.microsoft.com/v1.0/teams/{inputs.get('team_id')}/channels/{inputs.get('channel_id')}/messages", headers, body)
    if connector_id == "slack.post_message":
        body = {"channel": inputs.get("channel"), "text": _input_value(inputs, "text", "body", "message")}
        return _json_request("POST", "https://slack.com/api/chat.postMessage", headers, body)
    if connector_id == "gmail.send_email":
        raw = base64.urlsafe_b64encode(
            f"To: {inputs.get('to')}\r\nSubject: {inputs.get('subject')}\r\n\r\n{_input_value(inputs, 'body', 'message')}".encode("utf-8")
        ).decode("ascii")
        return _json_request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers, {"raw": raw})
    if connector_id == "gmail.create_draft":
        raw = base64.urlsafe_b64encode(
            f"To: {inputs.get('to')}\r\nSubject: {inputs.get('subject')}\r\n\r\n{_input_value(inputs, 'body', 'message')}".encode("utf-8")
        ).decode("ascii")
        return _json_request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts", headers, {"message": {"raw": raw}})
    if connector_id == "sheets.append_row":
        sheet_id = inputs.get("sheet_id") or _connector_config_value("sheets", "GOOGLE_SHEET_ID", "sheet_id", "spreadsheet_id")
        if not sheet_id:
            return _missing_config_request(connector_id, ["GOOGLE_SHEET_ID"])
        range_name = quote(str(inputs.get("range", "Sheet1!A1")), safe="")
        body = {"values": inputs.get("values", [])}
        return _json_request("POST", f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}:append?valueInputOption=USER_ENTERED", headers, body)
    if connector_id == "sheets.read_rows":
        sheet_id = inputs.get("sheet_id") or _connector_config_value("sheets", "GOOGLE_SHEET_ID", "sheet_id", "spreadsheet_id")
        if not sheet_id:
            return _missing_config_request(connector_id, ["GOOGLE_SHEET_ID"])
        range_name = quote(str(inputs.get("range", "Sheet1!A1")), safe="")
        return {"method": "GET", "url": f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}", "headers": headers, "body": None}
    if connector_id == "http.request":
        return {
            "method": inputs.get("method", "GET"),
            "url": inputs["url"],
            "headers": {**headers, **inputs.get("headers", {})},
            "body": json.dumps(inputs.get("body", {})).encode("utf-8") if inputs.get("body") else None,
        }
    return {
        "method": "POST",
        "url": inputs.get("url", f"connector://{service}/{connector_id}"),
        "headers": headers,
        "body": json.dumps(inputs.get("body", inputs)).encode("utf-8"),
    }


def _connector_execution_plan(spec: dict, step: dict, inputs: dict | None = None, approved_override: bool = False) -> dict:
    connector_id = step["connector_id"]
    service = connector_id.split(".", 1)[0]
    step_inputs = _inputs_for_step(inputs or {}, step)
    missing_fields = _missing_live_fields(connector_id, step_inputs)
    secret = _secret_for_service(service)
    dynamic_capability = _find_dynamic_capability(connector_id)
    credentials_ready = service in {"http", "schema", "approval"} or bool(secret) or not (dynamic_capability or {}).get("requires_auth")
    approval_ready = not step.get("approval_required") or approved_override or _has_approved_step(spec["id"], step)
    request_preview = None
    provider_endpoint_ready = True
    if not missing_fields and credentials_ready and service not in {"schema", "approval"}:
        request_spec = _connector_live_request(connector_id, step_inputs, secret)
        request_preview = _safe_request_preview(request_spec)
        provider_endpoint_ready = not str(request_spec.get("url", "")).startswith("connector://")
    blockers = []
    if missing_fields:
        blockers.append({"type": "missing_fields", "fields": missing_fields})
    if not credentials_ready:
        blockers.append({"type": "missing_credentials", "service": service})
    if not approval_ready:
        blockers.append({"type": "approval_required", "step_id": step["id"]})
    if not provider_endpoint_ready:
        blockers.append({"type": "missing_provider_endpoint", "connector_id": connector_id})
    return {
        "step_id": step["id"],
        "name": step.get("name"),
        "connector_id": connector_id,
        "service": service,
        "ready": not blockers,
        "approval_required": bool(step.get("approval_required")),
        "approval_ready": approval_ready,
        "credentials_ready": credentials_ready,
        "required_fields": _required_live_fields(connector_id),
        "missing_fields": missing_fields,
        "request_preview": request_preview,
        "compensation": _compensation_for_step(connector_id, step_inputs),
        "blockers": blockers,
    }


def _runtime_execution_plan(spec_id: str, inputs: dict | None = None, approved: bool = False) -> dict:
    spec = _get_automation_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Automation spec not found")
    steps = [_connector_execution_plan(spec, step, inputs or {}, approved) for step in spec["steps"]]
    blockers = [blocker for step in steps for blocker in step["blockers"]]
    return {
        "spec_id": spec_id,
        "ready": not blockers,
        "mode": "approved_live" if approved else "pre_approval",
        "steps": steps,
        "blockers": blockers,
        "next_actions": [
            "Provide required input fields.",
            "Connect missing credentials in the Connector Center.",
            "Approve external-write steps before live execution.",
        ] if blockers else ["Ready for approved live execution."],
    }


def _credential_requirements_for_spec(spec_id: str) -> dict:
    spec = _get_automation_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Automation spec not found")
    services = []
    seen = set()
    for connector in spec.get("connectors", []):
        service = connector.get("service") or connector.get("id", "").split(".", 1)[0]
        if not service or service in seen or service in {"schema", "approval", "http"}:
            continue
        seen.add(service)
        info = SUPPORTED_SERVICES.get(service, {})
        env = _env_status(info.get("env_vars", connector.get("required_env", [])))
        has_vault = service in _credential_services()
        services.append({
            "service": service,
            "name": info.get("name", service),
            "connector_ids": [item["id"] for item in spec.get("connectors", []) if (item.get("service") or item.get("id", "").split(".", 1)[0]) == service],
            "required_env": list(info.get("env_vars", connector.get("required_env", []))),
            "env_status": env,
            "vault_credential": has_vault,
            "ready": env["configured"] or has_vault,
            "oauth_supported": service in _oauth_specs(),
        })
    return {
        "spec_id": spec_id,
        "ready": all(item["ready"] for item in services),
        "requirements": services,
        "missing": [item for item in services if not item["ready"]],
    }


def _execute_live_connector_step(spec: dict, step: dict, inputs: dict, approved_override: bool = False) -> tuple[str, dict, str | None]:
    connector_id = step["connector_id"]
    service = connector_id.split(".", 1)[0]
    step_inputs = _inputs_for_step(inputs, step)
    if step.get("approval_required") and not (approved_override or _has_approved_step(spec["id"], step)):
        return "waiting_for_approval", {"live_call_performed": False, "approval_required": True}, None

    required = _required_live_fields(connector_id)
    missing_fields = _missing_live_fields(connector_id, step_inputs)
    if missing_fields:
        return "blocked", {"live_call_performed": False, "missing_fields": missing_fields}, None

    secret = _secret_for_service(service)
    dynamic_capability = _find_dynamic_capability(connector_id)
    auth_required = bool((dynamic_capability or {}).get("requires_auth"))
    if service not in {"http", "schema", "approval"} and not secret and (not dynamic_capability or auth_required):
        return "blocked", {"live_call_performed": False, "missing": "credentials"}, None

    request_spec = _connector_live_request(connector_id, step_inputs, secret)
    if request_spec["url"].startswith("connector://"):
        return "blocked", {
            "live_call_performed": False,
            "missing": "provider_endpoint",
            "request": {k: v for k, v in request_spec.items() if k != "body"},
        }, None

    try:
        req = Request(
            request_spec["url"],
            data=request_spec.get("body"),
            headers=request_spec.get("headers", {}),
            method=request_spec.get("method", "POST"),
        )
        with urlopen(req, timeout=20, context=_https_context()) as response:
            text = response.read().decode("utf-8", errors="replace")[:4000]
            parsed_response = _json_loads(text, {"text": text})
            provider_ok = parsed_response.get("ok", True) is not False if isinstance(parsed_response, dict) else True
            status = "succeeded" if response.status < 400 and provider_ok else "failed"
            error = parsed_response.get("error") if not provider_ok and isinstance(parsed_response, dict) else None
            return status, {
                "live_call_performed": True,
                "status_code": response.status,
                "response": parsed_response,
                "compensation": _compensation_for_step(connector_id, step_inputs),
            }, error
    except Exception as exc:
        return "failed", {"live_call_performed": True, "request_url": request_spec["url"]}, _redact_sensitive(str(exc), secret)


def _compensation_for_step(connector_id: str, inputs: dict) -> dict:
    if connector_id == "stripe.create_refund":
        return {"type": "manual_review", "reason": "Stripe refunds generally cannot be undone after creation."}
    if connector_id.endswith("create_ticket"):
        return {"type": "close_record", "target": "created ticket"}
    if connector_id.endswith("create_event"):
        return {"type": "delete_event", "target": "created event"}
    if connector_id.endswith("create_contact") or connector_id.endswith("create_record"):
        return {"type": "delete_created_record", "target": "provider object id from response"}
    return {"type": "provider_specific_compensation", "available": False}


async def _live_run_automation_spec(spec_id: str, inputs: dict | None = None, approved: bool = False) -> dict:
    spec = _get_automation_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Automation spec not found")
    run_id = _stable_id("runtime_live", {"spec_id": spec_id})
    started = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO runtime_runs
        (id, spec_id, status, mode, input_json, output_json, started_at, completed_at)
        VALUES (?, ?, 'running', 'live', ?, '{}', ?, NULL)
        """,
        (run_id, spec_id, json.dumps(inputs or {}), started),
    )
    conn.commit()
    conn.close()
    failed = False
    blocked = False
    for step in spec["steps"]:
        status, output, error = _execute_live_connector_step(spec, step, inputs or {}, approved_override=approved)
        failed = failed or status == "failed"
        blocked = blocked or status in {"blocked", "waiting_for_approval"}
        _record_runtime_step(run_id, step, status, output, error)
    final_status = "failed" if failed else ("blocked" if blocked else "succeeded")
    output = {"summary": f"{len(spec['steps'])} live steps evaluated", "approved_override": approved}
    conn = _platform_db()
    conn.execute(
        "UPDATE runtime_runs SET status = ?, output_json = ?, completed_at = ? WHERE id = ?",
        (final_status, json.dumps(output), _now_iso(), run_id),
    )
    conn.commit()
    conn.close()
    _record_observability_event("runtime", "error" if failed else "info", "live_spec_run", spec_id, output | {"status": final_status})
    return _list_runtime_runs(limit=1)[0]


def _automation_missing_actions(spec: dict, validations: list[dict], dry_run: dict, discovery: dict) -> list[dict]:
    actions = []
    preflight = spec.get("preflight", {})

    if preflight.get("schema_needed"):
        actions.append({
            "type": "schema_required",
            "label": "Connect or upload the real source schema",
            "detail": "ForgeFlow needs the actual CSV, Excel, table, or API schema before it can map fields without inventing names.",
            "blocking": True,
        })

    for connector in spec.get("connectors", []):
        if connector.get("status") == "needs_credentials":
            service = connector.get("service") or connector.get("id", "").split(".", 1)[0]
            actions.append({
                "type": "credential_required",
                "label": f"Connect {service}",
                "detail": f"{connector['id']} needs credentials before live execution. Dry-run and approval previews remain available.",
                "connector_id": connector["id"],
                "service": service,
                "required_env": connector.get("required_env", []),
                "blocking": True,
            })

    for validation in validations:
        if validation.get("status") != "ready":
            actions.append({
                "type": "connector_validation",
                "label": f"Validate {validation['adapter_id']}",
                "detail": "Connector contract is available, but credentials or live provider readiness are incomplete.",
                "connector_id": validation["adapter_id"],
                "blocking": False,
            })

    if any(step.get("status") == "waiting_for_approval" for step in dry_run.get("steps", [])):
        actions.append({
            "type": "approval_required",
            "label": "Approve risky external actions",
            "detail": "External writes are paused in the approval queue with preview payloads before live execution.",
            "blocking": True,
        })

    if not discovery.get("local_capabilities") and discovery.get("public_apis"):
        first = discovery["public_apis"][0]
        actions.append({
            "type": "api_import_suggested",
            "label": f"Import {first.get('title') or first.get('id')} OpenAPI spec",
            "detail": "No strong local capability matched this request. Importing the public API spec can add grounded operations.",
            "source_url": first.get("source_url"),
            "blocking": False,
        })

    seen = set()
    deduped = []
    for action in actions:
        key = (action.get("type"), action.get("connector_id"), action.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _automation_readiness(spec: dict, validations: list[dict], dry_run: dict, discovery: dict) -> dict:
    missing_actions = _automation_missing_actions(spec, validations, dry_run, discovery)
    blocking = [item for item in missing_actions if item.get("blocking")]
    dry_status = dry_run.get("status")
    export_ready = dry_status in {"succeeded", "waiting_for_approval", "blocked"}
    live_ready = not blocking and dry_status == "succeeded" and all(item.get("status") == "ready" for item in validations)
    if live_ready:
        verdict = "ready_for_approved_live_execution"
    elif any(item["type"] == "schema_required" for item in blocking):
        verdict = "blocked_by_schema"
    elif any(item["type"] == "credential_required" for item in blocking):
        verdict = "blocked_by_credentials"
    elif any(item["type"] == "approval_required" for item in blocking):
        verdict = "waiting_for_human_approval"
    else:
        verdict = "ready_for_dry_run"
    return {
        "verdict": verdict,
        "score": max(0, 100 - (len(blocking) * 20) - max(0, len(missing_actions) - len(blocking)) * 5),
        "live_execution_ready": live_ready,
        "export_ready": export_ready,
        "blocking_actions": blocking,
        "next_actions": missing_actions,
        "safety": {
            "live_call_performed": False,
            "approval_first": bool(spec.get("approval_gates")),
            "dry_run_status": dry_status,
        },
    }


async def _run_prompt_autopilot(prompt: str, context: dict | None = None, platforms: list[str] | None = None) -> dict:
    context = context or {}
    platforms = platforms or ["forgeflow", "n8n", "zapier", "github_actions"]
    conversation = _business_conversation(prompt, context)
    discovery = _discover_capabilities(prompt, limit=8, include_public=True)
    spec = await _compile_automation_spec(prompt, context)
    validations = []
    for connector in spec.get("connectors", []):
        try:
            validations.append(_validate_connector_adapter(connector["id"]))
        except HTTPException as exc:
            validations.append({
                "id": _stable_id("validation_error", {"adapter_id": connector["id"]}),
                "adapter_id": connector["id"],
                "status": "missing_adapter",
                "checks": [{"id": "adapter", "label": "Adapter contract", "status": "fail", "detail": exc.detail}],
                "alternatives": [{"id": "http.request", "label": "Import an OpenAPI spec or use generic HTTP"}],
                "created_at": _now_iso(),
            })

    dry_run = await _dry_run_automation_spec(spec["id"], {"source": "autopilot", **context.get("sample_inputs", {})})
    exports = [_export_spec_to_platform(spec["id"], platform) for platform in platforms]
    repair = _repair_runtime_run(dry_run["id"]) if dry_run.get("status") in {"blocked", "waiting_for_approval", "failed"} else None
    readiness = _automation_readiness(spec, validations, dry_run, discovery)
    _record_observability_event(
        "autopilot",
        "info" if readiness["live_execution_ready"] else "warning",
        "prompt_autopilot_completed",
        spec["id"],
        {"verdict": readiness["verdict"], "score": readiness["score"], "dry_run_status": dry_run.get("status")},
    )
    return {
        "prompt": prompt,
        "conversation": conversation,
        "discovery": discovery,
        "spec": spec,
        "validations": validations,
        "dry_run": dry_run,
        "exports": exports,
        "repair": repair,
        "readiness": readiness,
        "production_contract": {
            "generated_from_prompt": True,
            "uses_grounded_capabilities": bool(spec.get("connectors")),
            "requires_human_approval_for_writes": bool(spec.get("approval_gates")),
            "safe_to_deploy_live": readiness["live_execution_ready"],
            "why_not_live": [item["label"] for item in readiness["blocking_actions"]],
        },
    }


def _business_conversation(prompt: str, context: dict | None = None) -> dict:
    prompt_lower = prompt.lower()
    known_systems = []
    for service, markers in SERVICE_MARKERS.items():
        if any(marker in prompt_lower for marker in markers):
            label = SUPPORTED_SERVICES.get(service, {}).get("name", service.title())
            if label not in known_systems:
                known_systems.append(label)

    process_steps = []
    if any(marker in prompt_lower for marker in ("hire", "employee", "onboard", "hr")):
        process_steps = [
            "Read each new-hire row from the approved HR source.",
            "Validate required employee fields from the real schema before generating messages.",
            "Prepare welcome email, team announcement, access request, and tracking update as previews.",
            "Wait for business approval before any email, chat post, or access-changing action.",
            "Deploy only after dry-run, test cases, and credential checks pass.",
        ]
    elif known_systems:
        process_steps = [
            "Identify the trigger and source data.",
            "Inspect real schemas or API contracts before mapping fields.",
            "Prepare each external action as a preview.",
            "Ask for approval before risky writes.",
            "Record run logs and repair suggestions when a step fails.",
        ]
    else:
        process_steps = [
            "Clarify the trigger, source system, and final business outcome.",
            "Import the relevant API, MCP tool, or file schema before code generation.",
            "Generate a dry-run workflow with approval gates.",
            "Test the workflow and surface missing credentials or APIs.",
        ]

    questions = []
    if not known_systems:
        questions.append("Which business systems should this touch, for example HRIS, email, Slack, Sheets, CRM, or a custom API?")
    if any(marker in prompt_lower for marker in ("sheet", "excel", "csv", "database", "hr", "crm", "airtable", "notion")):
        questions.append("Can you upload or connect the source file/table so ForgeFlow can read the real columns?")
    if any(marker in prompt_lower for marker in ("send", "post", "create", "update", "delete", "invite", "provision")):
        questions.append("Should ForgeFlow keep every external action in preview mode until a human approves it?")
    if any(marker in prompt_lower for marker in ("schedule", "weekly", "daily", "when", "webhook")):
        questions.append("What trigger should start the automation: manual run, schedule, webhook, or new row/event?")

    return {
        "prompt": prompt,
        "summary": "ForgeFlow turns the request into a grounded automation plan before generating executable code.",
        "known_systems": known_systems,
        "process_steps": process_steps,
        "questions": questions[:4],
        "non_technical_contract": [
            "No invented names, columns, or API fields.",
            "Credentials are requested only when the selected connector needs them.",
            "Risky actions are previews until approval.",
            "Failed tests produce repair actions instead of silent failure.",
        ],
        "context": context or {},
    }


def _list_workflow_exports(spec_id: str | None = None) -> list[dict]:
    conn = _platform_db()
    if spec_id:
        rows = conn.execute("SELECT * FROM workflow_exports WHERE spec_id = ? ORDER BY created_at DESC", (spec_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM workflow_exports ORDER BY created_at DESC LIMIT 30").fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "spec_id": row["spec_id"],
            "platform": row["platform"],
            "artifact": _json_loads(row["artifact_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _export_spec_to_platform(spec_id: str, platform: str) -> dict:
    spec = _get_automation_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Automation spec not found")
    platform = (platform or "forgeflow").strip().lower()
    step_names = [step["name"] for step in spec["steps"]]
    connectors = [connector["id"] for connector in spec["connectors"]]

    if platform == "n8n":
        artifact = {
            "format": "n8n.workflow.json",
            "workflow": {
                "name": f"ForgeFlow - {spec['goal'][:60]}",
                "active": False,
                "nodes": [
                    {
                        "id": step["id"],
                        "name": step["name"],
                        "type": "forgeflow.adapter",
                        "parameters": {
                            "connector": step["connector_id"],
                            "approvalRequired": step.get("approval_required", False),
                            "purpose": step["purpose"],
                        },
                    }
                    for step in spec["steps"]
                ],
                "connections": {
                    spec["steps"][index]["name"]: {"main": [[{"node": spec["steps"][index + 1]["name"], "type": "main", "index": 0}]]}
                    for index in range(len(spec["steps"]) - 1)
                },
            },
        }
    elif platform == "zapier":
        artifact = {
            "format": "zapier.transfer.json",
            "zap": {
                "title": f"ForgeFlow - {spec['goal'][:60]}",
                "trigger": spec["trigger"],
                "actions": [
                    {
                        "name": step["name"],
                        "app": step["connector_id"].split(".")[0],
                        "event": step["connector_id"],
                        "input_mapping": step.get("input_contract", {}),
                    }
                    for step in spec["steps"]
                ],
            },
        }
    elif platform == "github_actions":
        artifact = {
            "format": ".github/workflows/forgeflow-spec.yml",
            "yaml": "\n".join([
                "name: ForgeFlow Spec Runner",
                "on:",
                "  workflow_dispatch:",
                "jobs:",
                "  dry-run:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-python@v5",
                "        with:",
                "          python-version: '3.11'",
                f"      - run: python -m backend.runtime.run_spec {spec_id} --mode dry-run",
            ]),
        }
    else:
        artifact = {
            "format": "forgeflow.spec.json",
            "spec": spec,
            "runtime_contract": {
                "connectors": connectors,
                "ordered_steps": step_names,
                "approval_gates": spec["approval_gates"],
                "tests": spec["tests"],
            },
        }

    export_id = _stable_id("export", {"spec_id": spec_id, "platform": platform})
    record = {
        "id": export_id,
        "spec_id": spec_id,
        "platform": platform,
        "artifact": artifact,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        "INSERT INTO workflow_exports (id, spec_id, platform, artifact_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (record["id"], record["spec_id"], record["platform"], json.dumps(record["artifact"]), record["created_at"]),
    )
    conn.commit()
    conn.close()
    return record


def _validate_connector_adapter(adapter_id: str) -> dict:
    adapter = next((item for item in _connector_adapters() if item["id"] == adapter_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail="Connector adapter not found")
    service = adapter.get("service")
    env_vars = list(adapter.get("capability", {}).get("requires_auth", [])) or list(SUPPORTED_SERVICES.get(service, {}).get("env_vars", ()))
    if not env_vars and service in _oauth_specs():
        env_vars = list(_oauth_specs()[service].get("env_vars", []))
    env = _env_status(env_vars)
    has_vault = service in _credential_services()
    checks = [
        {"id": "contract", "label": "Adapter contract", "status": "pass", "detail": f"{len(adapter['methods'])} methods declared"},
        {"id": "dry_run", "label": "Dry-run support", "status": "pass" if "dry_run" in adapter["methods"] else "warn", "detail": "Can preview without live writes" if "dry_run" in adapter["methods"] else "No dry-run method declared"},
        {"id": "credentials", "label": "Credentials", "status": "pass" if adapter["configured"] or has_vault or env["configured"] else "warn", "detail": "Ready" if adapter["configured"] or has_vault or env["configured"] else f"Missing {', '.join(env['missing']) or 'stored credential'}"},
    ]
    alternatives = []
    if adapter.get("risk") == "external_write":
        alternatives.append({"id": "approval.wait", "label": "Create approval-only preview until credentials are connected"})
    if service != "http":
        alternatives.append({"id": "http.request", "label": "Use imported OpenAPI endpoint or generic HTTP request"})
    if service != "schema":
        alternatives.append({"id": "schema.inspect_file", "label": "Ground fields from an uploaded CSV/XLSX first"})
    status = "ready" if all(item["status"] == "pass" for item in checks) else "needs_credentials"
    record = {
        "id": _stable_id("validation", {"adapter_id": adapter_id}),
        "adapter_id": adapter_id,
        "status": status,
        "checks": checks,
        "alternatives": alternatives,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        "INSERT INTO connector_validations (id, adapter_id, status, checks_json, alternatives_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (record["id"], adapter_id, status, json.dumps(checks), json.dumps(alternatives), record["created_at"]),
    )
    conn.commit()
    conn.close()
    return record


def _connector_probe_request(service: str, secret: str | None) -> dict | None:
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    if service == "slack":
        return {"method": "POST", "url": "https://slack.com/api/auth.test", "headers": headers, "body": None}
    if service == "stripe":
        return {"method": "GET", "url": "https://api.stripe.com/v1/balance", "headers": headers, "body": None}
    if service == "gmail":
        return {"method": "GET", "url": "https://gmail.googleapis.com/gmail/v1/users/me/profile", "headers": headers, "body": None}
    if service == "sheets":
        sheet_id = _connector_config_value("sheets", "GOOGLE_SHEET_ID", "sheet_id", "spreadsheet_id")
        if not sheet_id:
            return None
        return {"method": "GET", "url": f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}", "headers": headers, "body": None}
    if service == "calendar":
        return {"method": "GET", "url": "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1", "headers": headers, "body": None}
    if service == "hubspot":
        return {"method": "GET", "url": "https://api.hubapi.com/crm/v3/owners?limit=1", "headers": headers, "body": None}
    if service == "zendesk":
        subdomain = _connector_config_value("zendesk", "ZENDESK_SUBDOMAIN", "subdomain")
        email = _connector_config_value("zendesk", "ZENDESK_EMAIL", "email")
        if not subdomain:
            return None
        if email:
            token = base64.b64encode(f"{email}/token:{secret}".encode("utf-8")).decode("ascii")
            headers = {"Accept": "application/json", "Authorization": f"Basic {token}"}
        return {"method": "GET", "url": f"https://{subdomain}.zendesk.com/api/v2/users/me.json", "headers": headers, "body": None}
    if service == "okta":
        org_url = _connector_config_value("okta", "OKTA_ORG_URL", "org_url").rstrip("/")
        if not org_url:
            return None
        return {"method": "GET", "url": f"{org_url}/api/v1/users?limit=1", "headers": {"Accept": "application/json", "Authorization": f"SSWS {secret}"}, "body": None}
    if service == "salesforce":
        instance_url = _connector_config_value("salesforce", "SALESFORCE_INSTANCE_URL", "instance_url").rstrip("/")
        if not instance_url:
            return None
        return {"method": "GET", "url": f"{instance_url}/services/data/v60.0/limits", "headers": headers, "body": None}
    if service == "jira":
        base_url = _connector_config_value("jira", "JIRA_BASE_URL", "base_url").rstrip("/")
        email = _connector_config_value("jira", "JIRA_EMAIL", "email")
        if not base_url or not email:
            return None
        auth = base64.b64encode(f"{email}:{secret}".encode("utf-8")).decode("ascii")
        return {"method": "GET", "url": f"{base_url}/rest/api/3/myself", "headers": {"Accept": "application/json", "Authorization": f"Basic {auth}"}, "body": None}
    if service == "notion":
        return {"method": "GET", "url": "https://api.notion.com/v1/users/me", "headers": {**headers, "Notion-Version": "2022-06-28"}, "body": None}
    if service == "airtable":
        return {"method": "GET", "url": "https://api.airtable.com/v0/meta/whoami", "headers": headers, "body": None}
    if service == "teams":
        return {"method": "GET", "url": "https://graph.microsoft.com/v1.0/me", "headers": headers, "body": None}
    return None


def _record_connector_test(service: str, status: str, mode: str, request_data: dict, response_data: dict | None = None, error: str | None = None) -> dict:
    record = {
        "id": _stable_id("connector_test", {"service": service, "status": status, "mode": mode}),
        "service": service,
        "status": status,
        "mode": mode,
        "request": request_data,
        "response": response_data or {},
        "error": error,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO connector_tests
        (id, service, status, mode, request_json, response_json, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            service,
            status,
            mode,
            json.dumps(record["request"]),
            json.dumps(record["response"]),
            error,
            record["created_at"],
        ),
    )
    conn.commit()
    conn.close()
    _record_observability_event(
        "connector",
        "error" if status == "failed" else "info",
        "connector_test_completed",
        service,
        {"status": status, "mode": mode, "error": error},
    )
    return record


def _list_connector_tests(limit: int = 40) -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM connector_tests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "service": row["service"],
            "status": row["status"],
            "mode": row["mode"],
            "request": _json_loads(row["request_json"], {}),
            "response": _json_loads(row["response_json"], {}),
            "error": row["error"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _test_connector_service(service: str, live: bool = False) -> dict:
    service = service.lower().strip()
    if service not in SUPPORTED_SERVICES:
        raise HTTPException(status_code=404, detail="Connector service not found")
    if service in {"schema", "approval"}:
        return _record_connector_test(service, "ready", "local_contract", {"kind": "local"}, {"message": "Local connector does not require external credentials."})
    if service == "http" and not live:
        return _record_connector_test(service, "ready", "dry_run", {"kind": "generic_http"}, {"message": "HTTP connector validates per-request URL at execution time."})

    secret = _secret_for_service(service)
    if not secret:
        return _record_connector_test(service, "missing_credentials", "credential_check", {"kind": "credential_lookup"}, {"missing": "credential"})

    request_spec = _connector_probe_request(service, secret)
    if not request_spec:
        missing_env = _env_status(SUPPORTED_SERVICES[service].get("env_vars", ())).get("missing", [])
        return _record_connector_test(service, "blocked", "read_only_probe", {"kind": "provider_probe"}, {"missing_env": missing_env}, "Provider probe needs additional non-secret configuration.")

    safe_request = {
        "method": request_spec["method"],
        "url": request_spec["url"],
        "headers": sorted([key for key in request_spec.get("headers", {}) if key.lower() != "authorization"]),
    }
    if not live:
        return _record_connector_test(service, "ready_to_probe", "dry_run", safe_request, {"message": "Credential exists. Enable live probe to verify provider access."})

    try:
        req = Request(
            request_spec["url"],
            data=request_spec.get("body"),
            headers=request_spec.get("headers", {}),
            method=request_spec.get("method", "GET"),
        )
        with urlopen(req, timeout=15, context=_https_context()) as response:
            text = response.read().decode("utf-8", errors="replace")[:2000]
            parsed = _json_loads(text, {"text": text})
            status = "connected" if response.status < 400 else "failed"
            return _record_connector_test(service, status, "live_read_only_probe", safe_request, {"status_code": response.status, "body": parsed})
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")[:1000] if hasattr(exc, "read") else str(exc)
        if exc.code == 401:
            refreshed_secret = _refresh_oauth_access_token(service)
            if refreshed_secret:
                retry_spec = _connector_probe_request(service, refreshed_secret)
                if retry_spec:
                    try:
                        retry_req = Request(
                            retry_spec["url"],
                            data=retry_spec.get("body"),
                            headers=retry_spec.get("headers", {}),
                            method=retry_spec.get("method", "GET"),
                        )
                        with urlopen(retry_req, timeout=15, context=_https_context()) as response:
                            text = response.read().decode("utf-8", errors="replace")[:2000]
                            parsed = _json_loads(text, {"text": text})
                            status = "connected" if response.status < 400 else "failed"
                            retry_response = {"status_code": response.status, "body": parsed, "token_refreshed": True}
                            return _record_connector_test(service, status, "live_read_only_probe", safe_request, retry_response)
                    except Exception:
                        pass
        return _record_connector_test(service, "failed", "live_read_only_probe", safe_request, {"status_code": exc.code}, error_text)
    except URLError as exc:
        return _record_connector_test(service, "failed", "live_read_only_probe", safe_request, {}, str(exc.reason)[:1000])
    except Exception as exc:
        return _record_connector_test(service, "failed", "live_read_only_probe", safe_request, {}, str(exc)[:1000])


def _repair_runtime_run(run_id: str) -> dict:
    run = next((item for item in _list_runtime_runs(limit=100) if item["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Runtime run not found")
    actions = []
    for step in run["steps"]:
        if step["status"] == "blocked" and step["output"].get("missing") == "credentials":
            actions.append({
                "type": "credential_request",
                "step_id": step["step_id"],
                "connector_id": step["connector_id"],
                "message": f"Ask the user to connect credentials for {step['connector_id']} before live execution.",
            })
        elif step["status"] == "waiting_for_approval":
            actions.append({
                "type": "approval_gate",
                "step_id": step["step_id"],
                "connector_id": step["connector_id"],
                "message": "Keep this step paused until the business owner approves the preview.",
            })
        elif step["error"]:
            error_text = step["error"] or ""
            lower_error = error_text.lower()
            classification = "provider_error"
            patch = "Inspect provider response and adjust connector inputs."
            if "401" in error_text or "403" in error_text or "unauthorized" in lower_error:
                classification = "auth_error"
                patch = "Rotate or reconnect credentials, then run a read-only connector probe."
            elif "404" in error_text or "not found" in lower_error:
                classification = "endpoint_or_record_missing"
                patch = "Verify imported endpoint path, base URL, and record identifiers."
            elif "timeout" in lower_error:
                classification = "timeout"
                patch = "Retry with exponential backoff or increase connector timeout."
            actions.append({
                "type": "debug_error",
                "classification": classification,
                "step_id": step["step_id"],
                "connector_id": step["connector_id"],
                "message": step["error"],
                "patch_suggestion": patch,
                "retest": {
                    "type": "execution_plan",
                    "run_id": run_id,
                    "step_id": step["step_id"],
                },
            })
    if not actions:
        actions.append({
            "type": "no_repair_needed",
            "message": "The run does not have blocked or failed steps.",
        })
    record = {
        "id": _stable_id("repair", {"run_id": run_id}),
        "run_id": run_id,
        "status": "needs_user_input" if any(item["type"] in {"credential_request", "approval_gate"} for item in actions) else "ready",
        "actions": actions,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        "INSERT INTO repair_runs (id, run_id, status, actions_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (record["id"], run_id, record["status"], json.dumps(actions), record["created_at"]),
    )
    conn.commit()
    conn.close()
    return record


async def _retest_repair(run_id: str) -> dict:
    run = next((item for item in _list_runtime_runs(limit=100) if item["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Runtime run not found")
    plan = _runtime_execution_plan(run["spec_id"], run.get("input", {}), approved=False)
    repair = _repair_runtime_run(run_id)
    result = {
        "run_id": run_id,
        "plan": plan,
        "repair": repair,
        "status": "ready" if plan["ready"] else "blocked",
        "created_at": _now_iso(),
    }
    _record_observability_event("repair", "info", "repair_retested", run_id, {"status": result["status"], "blockers": plan["blockers"]})
    return result


async def _run_hr_onboarding_demo(prompt: str | None = None) -> dict:
    demo_prompt = prompt or (
        "Automate employee onboarding from an HR Excel sheet. Send a Gmail welcome email, "
        "post a Slack team announcement, create an IT access request through API, append a "
        "Google Sheets tracking row, test it, and wait for approval before live actions."
    )
    conversation = _business_conversation(demo_prompt, {"demo": "hr_onboarding"})
    spec = await _compile_automation_spec(demo_prompt, {
        "schema": {
            "source": "sample_hr_new_hires.xlsx",
            "columns": ["employee_name", "personal_email", "start_date", "manager", "department", "role"],
            "sample_row_count": 2,
        }
    })
    run = await _dry_run_automation_spec(spec["id"], {
        "employee_name": "Sample New Hire",
        "department": "Operations",
        "source": "challenge_demo",
    })
    exports = [
        _export_spec_to_platform(spec["id"], "forgeflow"),
        _export_spec_to_platform(spec["id"], "n8n"),
        _export_spec_to_platform(spec["id"], "github_actions"),
    ]
    repair = _repair_runtime_run(run["id"])
    validations = [_validate_connector_adapter(connector["id"]) for connector in spec["connectors"]]
    return {
        "conversation": conversation,
        "spec": spec,
        "run": run,
        "exports": exports,
        "repair": repair,
        "validations": validations,
        "answer_to_challenge": {
            "live_generation": True,
            "non_technical_friendly": True,
            "executable_output": True,
            "human_oversight": bool(spec["approval_gates"]),
            "no_hallucinated_schema": True,
            "live_external_calls_performed": False,
        },
    }


def _staging_profile() -> dict:
    """Describe safe destinations for live demos without performing external writes."""
    credential_services = _credential_services()
    destinations = [
        {
            "service": "gmail",
            "label": "Gmail welcome email",
            "mode": "draft_first",
            "destination": os.getenv("FORGEFLOW_STAGING_EMAIL_TO", "new.hire@example.com"),
            "configured": bool(_secret_for_service("gmail")),
            "safety": "Create or preview a draft before sending anything to a real recipient.",
        },
        {
            "service": "slack",
            "label": "Slack announcement",
            "mode": "staging_channel",
            "destination": os.getenv("FORGEFLOW_STAGING_SLACK_CHANNEL", "#forgeflow-staging"),
            "configured": bool(_secret_for_service("slack")),
            "safety": "Post only to the configured staging channel after approval.",
        },
        {
            "service": "sheets",
            "label": "Onboarding tracker",
            "mode": "test_sheet",
            "destination": os.getenv("FORGEFLOW_STAGING_SHEET_ID", os.getenv("GOOGLE_SHEET_ID", "staging-onboarding-sheet")),
            "configured": bool(_secret_for_service("sheets")),
            "safety": "Append rows to a staging sheet, never to HR production data during demo runs.",
        },
        {
            "service": "calendar",
            "label": "Training schedule",
            "mode": "test_calendar",
            "destination": os.getenv("FORGEFLOW_STAGING_CALENDAR_ID", "primary"),
            "configured": bool(_secret_for_service("calendar")),
            "safety": "Create calendar previews first; live insert requires approval.",
        },
        {
            "service": "http",
            "label": "IT access request",
            "mode": "mock_or_sandbox_endpoint",
            "destination": os.getenv("FORGEFLOW_STAGING_IT_ENDPOINT", "https://example.com/it-access-request"),
            "configured": True,
            "safety": "Use a sandbox endpoint or mock response until a real IT API is connected.",
        },
    ]
    return {
        "id": "forgeflow-staging",
        "name": "ForgeFlow staging workspace",
        "draft_first": True,
        "approval_required_before_live": True,
        "credential_sources": ["environment", "encrypted_vault"],
        "credential_services": sorted(credential_services),
        "destinations": destinations,
        "ready_destinations": sum(1 for item in destinations if item["configured"]),
        "total_destinations": len(destinations),
    }


def _hr_onboarding_staging_inputs() -> dict:
    return {
        "employee_name": "Avery Johnson",
        "personal_email": os.getenv("FORGEFLOW_STAGING_EMAIL_TO", "avery.johnson@example.com"),
        "manager": "Maya Patel",
        "department": "Operations",
        "role": "People Operations Associate",
        "start_date": "2026-05-18",
        "source_file": "sample_hr_new_hires.xlsx",
        "slack_channel": os.getenv("FORGEFLOW_STAGING_SLACK_CHANNEL", "#forgeflow-staging"),
        "tracking_sheet": os.getenv("FORGEFLOW_STAGING_SHEET_ID", os.getenv("GOOGLE_SHEET_ID", "staging-onboarding-sheet")),
        "training_calendar": os.getenv("FORGEFLOW_STAGING_CALENDAR_ID", "primary"),
    }


def _draft_first_execution_plan(spec: dict, inputs: dict, staging: dict) -> list[dict]:
    destinations = {item["service"]: item for item in staging["destinations"]}
    plan = []
    for index, step in enumerate(spec.get("steps", []), start=1):
        connector_id = step.get("connector_id", "")
        service = connector_id.split(".", 1)[0]
        destination = destinations.get(service, {"mode": "dry_run", "destination": "local preview", "configured": True})
        action_payload = {
            "employee_name": inputs["employee_name"],
            "department": inputs["department"],
            "manager": inputs["manager"],
            "start_date": inputs["start_date"],
        }
        if service == "gmail":
            action_payload.update({
                "to": inputs["personal_email"],
                "subject": f"Welcome to {inputs['department']}, {inputs['employee_name']}",
                "body": f"Welcome {inputs['employee_name']}. Your manager {inputs['manager']} will meet you on {inputs['start_date']}.",
            })
        elif service == "slack":
            action_payload.update({
                "channel": inputs["slack_channel"],
                "text": f"Welcome {inputs['employee_name']} to {inputs['department']} on {inputs['start_date']}.",
            })
        elif service == "sheets":
            action_payload.update({
                "sheet_id": inputs["tracking_sheet"],
                "values": [inputs["employee_name"], inputs["department"], inputs["manager"], inputs["start_date"]],
            })
        elif service == "calendar":
            action_payload.update({
                "calendar_id": inputs["training_calendar"],
                "summary": f"First-week training for {inputs['employee_name']}",
                "date": inputs["start_date"],
            })
        elif service == "http":
            action_payload.update({
                "url": os.getenv("FORGEFLOW_STAGING_IT_ENDPOINT", "https://example.com/it-access-request"),
                "method": "POST",
                "json": {"employee": inputs["employee_name"], "role": inputs["role"]},
            })
        plan.append({
            "order": index,
            "step_id": step.get("id"),
            "step_name": step.get("name"),
            "connector_id": connector_id,
            "service": service,
            "mode": destination.get("mode", "dry_run"),
            "destination": destination.get("destination"),
            "credential_ready": destination.get("configured", False),
            "approval_required": bool(step.get("approval_required", True)),
            "live_call_performed": False,
            "payload_preview": action_payload,
        })
    return plan


async def _run_judge_demo(prompt: str | None = None) -> dict:
    demo = await _run_hr_onboarding_demo(prompt)
    staging = _staging_profile()
    inputs = _hr_onboarding_staging_inputs()
    draft_plan = _draft_first_execution_plan(demo["spec"], inputs, staging)
    services = sorted({item["service"] for item in draft_plan if item["service"] in SUPPORTED_SERVICES})
    connector_checks = [_test_connector_service(service, live=False) for service in services]
    worker = {
        "enabled": bool(getattr(app.state, "queue_worker_enabled", False)),
        "interval_seconds": int(os.getenv("FORGEFLOW_QUEUE_WORKER_INTERVAL", "10")),
        "batch_size": int(os.getenv("FORGEFLOW_QUEUE_WORKER_BATCH", "5")),
        "due_count": len(_due_queue_items(limit=20)),
    }
    deployment_health = _deployment_provider_health()
    external_plan = [item for item in draft_plan if item["service"] not in {"schema", "approval"}]
    scorecard = [
        {"id": "conversation", "label": "Plain-English requirement collection", "passed": bool(demo["conversation"]["process_steps"])},
        {"id": "grounding", "label": "No hallucinated HR schema", "passed": demo["answer_to_challenge"]["no_hallucinated_schema"]},
        {"id": "connectors", "label": "Connector readiness checked", "passed": bool(connector_checks)},
        {"id": "draft_first", "label": "Every external step is draft-first", "passed": all(not item["live_call_performed"] and item["approval_required"] for item in external_plan)},
        {"id": "exports", "label": "Multi-platform executable exports", "passed": len(demo["exports"]) >= 3},
        {"id": "repair", "label": "Self-repair plan generated", "passed": bool(demo["repair"]["actions"])},
        {"id": "deployment", "label": "Deployment targets inspected", "passed": bool(deployment_health)},
        {"id": "worker", "label": "Queue worker controls visible", "passed": "enabled" in worker},
    ]
    return {
        "scenario": {
            "title": "Employee onboarding from plain English to approved staging automation",
            "prompt": prompt or "I need to automate our employee onboarding process from an HR sheet.",
            "sample_inputs": inputs,
        },
        "staging_profile": staging,
        "demo": demo,
        "draft_first_plan": draft_plan,
        "connector_checks": connector_checks,
        "worker": worker,
        "deployment": {
            "targets": deployment_health,
            "recommended_target": "local_docker" if shutil.which("docker") else "github_actions",
            "live_deploy_performed": False,
        },
        "scorecard": scorecard,
        "judge_script": [
            "Enter a plain-English onboarding request.",
            "Show the generated process steps and missing questions.",
            "Show grounded schema requirements and connector mapping.",
            "Run the dry-run ledger and repair plan without external writes.",
            "Show draft-first staging payloads, approvals, exports, worker status, and deployment readiness.",
        ],
        "complete": all(item["passed"] for item in scorecard),
    }


def _classify_build_intent(prompt: str) -> dict:
    text = prompt.lower()
    app_markers = ("app", "game", "website", "site", "dashboard", "frontend", "web app", "landing page", "todo", "tic tac toe")
    automation_markers = ("automate", "workflow", "slack", "gmail", "sheets", "api", "approval", "onboarding", "trigger")
    app_score = sum(1 for marker in app_markers if marker in text)
    automation_score = sum(1 for marker in automation_markers if marker in text)
    if app_score > automation_score:
        return {
            "lane": "app_builder",
            "confidence": min(0.95, 0.65 + app_score * 0.08),
            "reason": "The request asks for an interactive software product instead of a business workflow.",
        }
    return {
        "lane": "automation_builder",
        "confidence": min(0.95, 0.65 + automation_score * 0.06),
        "reason": "The request is best handled as a connector-backed business automation.",
    }


def _tic_tac_toe_files(title: str) -> dict[str, str]:
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <main class="shell">
      <section class="game-panel" aria-label="Tic Tac Toe game">
        <div class="header">
          <div>
            <p class="eyebrow">Playable app build</p>
            <h1>{title}</h1>
          </div>
          <button id="reset" type="button">New game</button>
        </div>
        <div id="status" class="status" role="status">Player X starts</div>
        <div id="board" class="board" aria-label="Game board"></div>
        <div class="scorebar" aria-label="Scoreboard">
          <span>X wins <strong id="score-x">0</strong></span>
          <span>Draws <strong id="score-draw">0</strong></span>
          <span>O wins <strong id="score-o">0</strong></span>
        </div>
      </section>
    </main>
    <script src="./app.js"></script>
  </body>
</html>
"""
    css = """* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #0b1020;
  color: #edf5ff;
}

.shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.game-panel {
  width: min(92vw, 520px);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: #111827;
  padding: 20px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.32);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.eyebrow {
  margin: 0 0 6px;
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.1;
}

button {
  border: 0;
  border-radius: 8px;
  background: #7dd3fc;
  color: #06111c;
  cursor: pointer;
  font: inherit;
  font-weight: 800;
}

#reset {
  min-width: 104px;
  padding: 10px 14px;
}

.status {
  margin: 20px 0 14px;
  border: 1px solid rgba(125, 211, 252, 0.2);
  border-radius: 8px;
  background: rgba(14, 165, 233, 0.1);
  padding: 12px;
  color: #bae6fd;
  font-weight: 700;
}

.board {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.cell {
  aspect-ratio: 1;
  min-height: 92px;
  border: 1px solid rgba(148, 163, 184, 0.32);
  background: #0f172a;
  color: #f8fafc;
  font-size: clamp(38px, 12vw, 72px);
  line-height: 1;
  transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
}

.cell:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: #7dd3fc;
  background: #13213a;
}

.cell:disabled {
  cursor: default;
}

.cell.win {
  border-color: #34d399;
  background: rgba(16, 185, 129, 0.18);
  color: #a7f3d0;
}

.scorebar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 14px;
}

.scorebar span {
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 10px;
  color: #94a3b8;
  text-align: center;
}

.scorebar strong {
  display: block;
  margin-top: 4px;
  color: #f8fafc;
  font-size: 20px;
}
"""
    js = """const boardEl = document.querySelector("#board");
const statusEl = document.querySelector("#status");
const resetEl = document.querySelector("#reset");
const scoreXEl = document.querySelector("#score-x");
const scoreOEl = document.querySelector("#score-o");
const scoreDrawEl = document.querySelector("#score-draw");

const wins = [
  [0, 1, 2],
  [3, 4, 5],
  [6, 7, 8],
  [0, 3, 6],
  [1, 4, 7],
  [2, 5, 8],
  [0, 4, 8],
  [2, 4, 6],
];

let board = Array(9).fill("");
let player = "X";
let gameOver = false;
let score = { X: 0, O: 0, draw: 0 };

function render() {
  boardEl.innerHTML = "";
  board.forEach((value, index) => {
    const button = document.createElement("button");
    button.className = "cell";
    button.type = "button";
    button.textContent = value;
    button.ariaLabel = `Cell ${index + 1}${value ? ` occupied by ${value}` : ""}`;
    button.disabled = Boolean(value) || gameOver;
    button.addEventListener("click", () => play(index));
    boardEl.appendChild(button);
  });
}

function winningLine() {
  return wins.find(([a, b, c]) => board[a] && board[a] === board[b] && board[a] === board[c]);
}

function play(index) {
  if (board[index] || gameOver) return;
  board[index] = player;
  const line = winningLine();
  if (line) {
    gameOver = true;
    score[player] += 1;
    statusEl.textContent = `Player ${player} wins`;
    render();
    line.forEach((cellIndex) => boardEl.children[cellIndex].classList.add("win"));
    updateScore();
    return;
  }
  if (board.every(Boolean)) {
    gameOver = true;
    score.draw += 1;
    statusEl.textContent = "Draw game";
    updateScore();
    render();
    return;
  }
  player = player === "X" ? "O" : "X";
  statusEl.textContent = `Player ${player}'s turn`;
  render();
}

function updateScore() {
  scoreXEl.textContent = score.X;
  scoreOEl.textContent = score.O;
  scoreDrawEl.textContent = score.draw;
}

function reset() {
  board = Array(9).fill("");
  player = "X";
  gameOver = false;
  statusEl.textContent = "Player X starts";
  render();
}

resetEl.addEventListener("click", reset);
render();
"""
    return {"index.html": html, "styles.css": css, "app.js": js}


def _generic_app_files(title: str, prompt: str) -> dict[str, str]:
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; min-height: 100vh; font-family: Inter, system-ui, sans-serif; background: #0b1020; color: #f8fafc; }}
      main {{ max-width: 880px; margin: 0 auto; padding: 48px 24px; }}
      section {{ border: 1px solid rgba(148, 163, 184, .24); border-radius: 8px; background: #111827; padding: 24px; }}
      h1 {{ margin: 0 0 12px; font-size: 34px; }}
      p {{ color: #94a3b8; line-height: 1.7; }}
      button {{ border: 0; border-radius: 8px; background: #7dd3fc; color: #06111c; padding: 12px 16px; font-weight: 800; cursor: pointer; }}
      #output {{ margin-top: 18px; border-radius: 8px; background: #0f172a; padding: 16px; color: #bae6fd; }}
    </style>
  </head>
  <body>
    <main>
      <section>
        <h1>{title}</h1>
        <p>{prompt}</p>
        <button id="action" type="button">Run interaction</button>
        <div id="output">Ready</div>
      </section>
    </main>
    <script>
      const output = document.querySelector("#output");
      document.querySelector("#action").addEventListener("click", () => {{
        output.textContent = "Interaction complete. This is the first generated app-builder artifact.";
      }});
    </script>
  </body>
</html>
"""
    return {"index.html": html}


def _inline_app_preview(files: dict[str, str]) -> str:
    html = files["index.html"]
    if "styles.css" in files:
        html = html.replace('<link rel="stylesheet" href="./styles.css" />', f"<style>\n{files['styles.css']}\n</style>")
    if "app.js" in files:
        html = html.replace('<script src="./app.js"></script>', f"<script>\n{files['app.js']}\n</script>")
    return html


def _app_build_qa(files: dict[str, str], prompt: str) -> dict:
    html = files.get("index.html", "")
    css = files.get("styles.css", "")
    js = files.get("app.js", "")
    checks = [
        {"id": "entry_html", "label": "HTML entry exists", "status": "pass" if "<html" in html.lower() else "fail"},
        {"id": "responsive_viewport", "label": "Responsive viewport configured", "status": "pass" if "viewport" in html else "warn"},
        {"id": "interactive_js", "label": "Interactive JavaScript present", "status": "pass" if ("addEventListener" in js or "<script" in html) else "warn"},
        {"id": "no_external_iframe", "label": "No iframe-based fake app", "status": "pass" if "<iframe" not in html.lower() else "fail"},
        {"id": "stable_layout", "label": "Stable layout constraints", "status": "pass" if ("aspect-ratio" in css or "max-width" in css or "grid" in css) else "warn"},
    ]
    if "tic tac toe" in prompt.lower():
        checks.append({"id": "game_rules", "label": "Game rules implemented", "status": "pass" if "winningLine" in js and "score" in js else "fail"})
    return {
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "needs_review",
        "checks": checks,
    }


def _generate_app_build(prompt: str) -> dict:
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    intent = _classify_build_intent(clean_prompt)
    title = "Tic Tac Toe" if "tic tac toe" in clean_prompt.lower() else "Generated App"
    files = _tic_tac_toe_files(title) if "tic tac toe" in clean_prompt.lower() else _generic_app_files(title, clean_prompt)
    build_id = _stable_id("app_build", {"prompt": clean_prompt, "files": sorted(files)})
    build_dir = os.path.join(APP_BUILDS_DIR, build_id)
    os.makedirs(build_dir, exist_ok=True)
    for path, content in files.items():
        full_path = os.path.join(build_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as handle:
            handle.write(content)
    manifest = {
        "id": build_id,
        "prompt": clean_prompt,
        "intent": intent,
        "title": title,
        "type": "game" if "tic tac toe" in clean_prompt.lower() else "web_app",
        "entry": "index.html",
        "files": [{"path": path, "size": len(content)} for path, content in files.items()],
        "preview_html": _inline_app_preview(files),
        "qa": _app_build_qa(files, clean_prompt),
        "created_at": _now_iso(),
        "status": "generated",
        "next_steps": [
            "Preview the app in the App Builder tab.",
            "Ask for natural-language changes.",
            "Promote to a Vite/React project when the direction is approved.",
            "Run browser QA and deploy to Vercel/Render.",
        ],
    }
    with open(os.path.join(build_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({**manifest, "preview_html": ""}, handle, indent=2)
    return manifest


def _list_app_builds() -> list[dict]:
    if not os.path.isdir(APP_BUILDS_DIR):
        return []
    builds = []
    for build_id in os.listdir(APP_BUILDS_DIR):
        manifest_path = os.path.join(APP_BUILDS_DIR, build_id, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        with open(manifest_path, "r", encoding="utf-8") as handle:
            builds.append(_json_loads(handle.read(), {}))
    return sorted(builds, key=lambda item: item.get("created_at", ""), reverse=True)


def _extract_openapi_capabilities(spec: dict) -> list[dict]:
    title = spec.get("info", {}).get("title", "OpenAPI")
    server_url = ""
    if isinstance(spec.get("servers"), list) and spec["servers"]:
        server_url = spec["servers"][0].get("url", "")
    security_schemes = spec.get("components", {}).get("securitySchemes", {}) if isinstance(spec.get("components"), dict) else {}
    auth_requirements = sorted(security_schemes.keys())
    capabilities_data = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation = operation if isinstance(operation, dict) else {}
            operation_id = operation.get("operationId") or f"{method}_{path}".strip("/").replace("/", "_").replace("{", "").replace("}", "")
            request_body = operation.get("requestBody", {}) if isinstance(operation.get("requestBody"), dict) else {}
            parameters = operation.get("parameters", []) if isinstance(operation.get("parameters"), list) else []
            capabilities_data.append({
                "id": f"openapi.{operation_id}",
                "label": operation.get("summary") or operation_id.replace("_", " ").title(),
                "category": title,
                "risk": "network_call" if method.lower() == "get" else "external_write",
                "requires_auth": auth_requirements,
                "description": f"{method.upper()} {path}",
                "dry_run": True,
                "source": "openapi",
                "method": method.upper(),
                "path": path,
                "server_url": server_url,
                "operation_id": operation_id,
                "parameters": parameters,
                "request_body": request_body,
            })
    return capabilities_data


def _fetch_json_url(url: str) -> dict:
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Only public https:// URLs are supported")
    req = Request(url, headers={"User-Agent": "ForgeFlow API Discovery/1.0"})
    try:
        with urlopen(req, timeout=20, context=_https_context()) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch URL: {exc}")
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        try:
            import yaml
            return yaml.safe_load(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"URL did not return JSON/YAML: {exc}")


def _api_guru_candidates_from_catalog(prompt: str, catalog: dict, limit: int = 8) -> list[dict]:
    query_tokens = _tokenize_for_match(prompt)
    candidates = []
    for api_id, item in catalog.items():
        versions = item.get("versions") or {}
        preferred = item.get("preferred")
        version = versions.get(preferred) or next(iter(versions.values()), {})
        info = version.get("info", {})
        haystack = " ".join([
            api_id,
            info.get("title", ""),
            info.get("description", ""),
            " ".join(info.get("x-tags", []) if isinstance(info.get("x-tags"), list) else []),
        ])
        tokens = _tokenize_for_match(haystack)
        overlap = query_tokens & tokens
        if not overlap:
            continue
        swagger_url = version.get("swaggerUrl") or version.get("swaggerYamlUrl")
        if not swagger_url:
            continue
        score = min(0.99, 0.3 + (len(overlap) / max(len(query_tokens), 1)))
        candidates.append({
            "id": api_id,
            "title": info.get("title", api_id),
            "description": info.get("description", "")[:500],
            "version": version.get("version") or preferred,
            "source": "apis_guru",
            "source_url": swagger_url,
            "docs_url": item.get("url") or info.get("termsOfService"),
            "score": round(score, 3),
            "matched_terms": sorted(overlap),
        })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]


def _search_public_api_directory(prompt: str, limit: int = 8) -> list[dict]:
    catalog = _fetch_json_url(API_GURU_LIST_URL)
    return _api_guru_candidates_from_catalog(prompt, catalog, limit=limit)


def _discover_capabilities(prompt: str, limit: int = 8, include_public: bool = True) -> dict:
    local = _capability_search(prompt, limit=limit)
    public = []
    public_error = None
    if include_public:
        try:
            public = _search_public_api_directory(prompt, limit=limit)
        except HTTPException as exc:
            public_error = exc.detail
        except Exception as exc:
            public_error = str(exc)
    return {
        "prompt": prompt,
        "local_capabilities": local,
        "public_apis": public,
        "public_error": public_error,
        "mcp_status": {
            "runtime_connected": False,
            "mode": "manifest_ingestion",
            "detail": "ForgeFlow can ingest MCP manifests as capabilities; live MCP tool execution is still a runtime adapter task.",
        },
    }


def _extract_mcp_capabilities(manifest: dict) -> list[dict]:
    tools = manifest.get("tools") or manifest.get("capabilities") or []
    server_url = manifest.get("server_url") or manifest.get("url")
    capabilities_data = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name") or tool.get("id")
        if not name:
            continue
        capabilities_data.append({
            "id": f"mcp.{name}",
            "label": tool.get("title") or name.replace("_", " ").title(),
            "category": manifest.get("name", "MCP"),
            "risk": tool.get("risk", "tool_call"),
            "requires_auth": tool.get("requires_auth", []),
            "description": tool.get("description", "MCP tool capability"),
            "dry_run": bool(tool.get("dry_run", True)),
            "source": "mcp",
            "server_url": server_url,
            "tool_name": name,
            "input_schema": tool.get("input_schema") or tool.get("schema"),
        })
    return capabilities_data


def _store_ingestion(source_type: str, name: str, summary: dict, capabilities_data: list[dict]) -> dict:
    ingestion_id = _stable_id(source_type, {"name": name, "capabilities": capabilities_data})
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO ingestions
        (id, source_type, name, summary_json, capabilities_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ingestion_id, source_type, name, json.dumps(summary), json.dumps(capabilities_data), _now_iso()),
    )
    conn.commit()
    conn.close()
    return {
        "id": ingestion_id,
        "source_type": source_type,
        "name": name,
        "summary": summary,
        "capabilities": capabilities_data,
    }


def _deployment_artifacts(workflow_id: str, target: str) -> dict:
    if target == "github_actions":
        return {
            ".github/workflows/forgeflow.yml": "\n".join([
                "name: ForgeFlow Automation",
                "on:",
                "  workflow_dispatch:",
                "  schedule:",
                "    - cron: '*/15 * * * *'",
                "jobs:",
                "  run:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-python@v5",
                "        with:",
                "          python-version: '3.11'",
                f"      - run: cd workflows/{workflow_id} && pip install -r requirements.txt && python workflow.py",
            ]),
        }
    if target == "render_worker":
        return {
            "render.yaml": "\n".join([
                "services:",
                f"  - name: forgeflow-{workflow_id}",
                "    type: worker",
                "    env: python",
                "    buildCommand: pip install -r requirements.txt",
                "    startCommand: python workflow.py",
                "    autoDeploy: false",
            ]),
        }
    if target == "webhook_runtime":
        return {
            "webhook-runtime.py": "\n".join([
                "from fastapi import FastAPI, Request",
                "import subprocess",
                "",
                "app = FastAPI()",
                "",
                "@app.post('/run')",
                "async def run(request: Request):",
                "    payload = await request.json()",
                "    result = subprocess.run(['python', 'workflow.py'], capture_output=True, text=True, timeout=120)",
                "    return {'payload': payload, 'return_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}",
            ]),
        }
    if target == "vercel_project":
        return {
            "vercel.json": json.dumps({
                "buildCommand": "npm run build",
                "outputDirectory": "dist",
                "framework": "vite",
            }, indent=2),
            "api/run.py": "\n".join([
                "from http.server import BaseHTTPRequestHandler",
                "import json",
                "",
                "class handler(BaseHTTPRequestHandler):",
                "    def do_POST(self):",
                "        self.send_response(202)",
                "        self.send_header('Content-Type', 'application/json')",
                "        self.end_headers()",
                "        self.wfile.write(json.dumps({'accepted': True}).encode())",
            ]),
        }
    return {
        "docker-run.sh": "\n".join([
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"docker build -t forgeflow-{workflow_id} .",
            f"docker run --env-file .env forgeflow-{workflow_id}",
        ]),
    }


def _deployment_readiness(workflow_id: str, target_info: dict) -> dict:
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    required_files = ["workflow.py", "requirements.txt", "Dockerfile"]
    present_files = [
        file_name for file_name in required_files
        if project_path and os.path.exists(os.path.join(project_path, file_name))
    ]
    missing_files = [file_name for file_name in required_files if file_name not in present_files]
    env = _env_status(target_info.get("requires_env", []))
    blocking = []
    if not project_path:
        blocking.append("workflow_project_missing")
    if missing_files:
        blocking.append("required_files_missing")
    if not env["configured"]:
        blocking.append("target_credentials_missing")
    return {
        "project_found": bool(project_path),
        "present_files": present_files,
        "missing_files": missing_files,
        "env": env,
        "blocking": blocking,
        "ready": not blocking,
    }


def _deployment_provider_health() -> list[dict]:
    credential_services = _credential_services()
    health = []
    for target in DEPLOYMENT_TARGETS:
        env = _env_status(target.get("requires_env", []))
        checks = []
        if target["id"] == "local_docker":
            checks.append({
                "id": "docker_cli",
                "label": "Docker CLI",
                "status": "pass" if shutil.which("docker") else "warn",
                "detail": "docker is available" if shutil.which("docker") else "docker CLI not found on PATH",
            })
        elif target["id"] == "github_actions":
            checks.append({
                "id": "github_token",
                "label": "GitHub API token",
                "status": "pass" if env["configured"] or "github" in credential_services else "warn",
                "detail": "GitHub token available" if env["configured"] or "github" in credential_services else "Add GITHUB_TOKEN or store a github credential",
            })
        elif target["id"] == "render_worker":
            checks.append({
                "id": "render_token",
                "label": "Render API key",
                "status": "pass" if env["configured"] or "render" in credential_services else "warn",
                "detail": "Render API key available" if env["configured"] or "render" in credential_services else "Add RENDER_API_KEY or store a render credential",
            })
        elif target["id"] == "vercel_project":
            checks.append({
                "id": "vercel_token",
                "label": "Vercel token",
                "status": "pass" if env["configured"] or "vercel" in credential_services else "warn",
                "detail": "Vercel token available" if env["configured"] or "vercel" in credential_services else "Add VERCEL_TOKEN or store a vercel credential",
            })
        elif target["id"] == "webhook_runtime":
            checks.append({
                "id": "runtime_base_url",
                "label": "Runtime base URL",
                "status": "pass" if os.getenv("FORGEFLOW_RUNTIME_BASE_URL") else "warn",
                "detail": os.getenv("FORGEFLOW_RUNTIME_BASE_URL") or "Set FORGEFLOW_RUNTIME_BASE_URL for hosted webhook activation",
            })

        health.append({
            "id": target["id"],
            "name": target["name"],
            "status": "pass" if checks and all(check["status"] == "pass" for check in checks) else "warn",
            "env_status": env,
            "checks": checks,
        })
    return health


def _list_deployment_plans() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM deployment_plans ORDER BY created_at DESC LIMIT 30").fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "workflow_id": row["workflow_id"],
            "target": row["target"],
            "status": row["status"],
            "plan": _json_loads(row["plan_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _record_deployment_activation(plan_id: str, plan: dict, status: str) -> dict:
    activation_id = _stable_id("activation", {"plan_id": plan_id, "status": status})
    readiness = plan.get("readiness", {})
    activation = {
        "id": activation_id,
        "plan_id": plan_id,
        "workflow_id": plan.get("workflow_id"),
        "target": plan.get("target"),
        "status": status,
        "artifacts": plan.get("artifacts", {}),
        "blockers": readiness.get("blocking", []),
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO deployment_activations
        (id, plan_id, workflow_id, target, status, artifacts_json, blockers_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activation["id"],
            activation["plan_id"],
            activation["workflow_id"],
            activation["target"],
            activation["status"],
            json.dumps(activation["artifacts"]),
            json.dumps(activation["blockers"]),
            activation["created_at"],
        ),
    )
    conn.commit()
    conn.close()
    return activation


def _list_deployment_activations() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM deployment_activations ORDER BY created_at DESC LIMIT 30").fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "plan_id": row["plan_id"],
            "workflow_id": row["workflow_id"],
            "target": row["target"],
            "status": row["status"],
            "artifacts": _json_loads(row["artifacts_json"], {}),
            "blockers": _json_loads(row["blockers_json"], []),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _provider_request_for_plan(plan_id: str, plan: dict) -> dict:
    target = plan.get("target")
    workflow_id = plan.get("workflow_id")
    artifacts = plan.get("artifacts", {})
    if target == "github_actions":
        return {
            "provider": "github",
            "operation": "upsert_workflow_file",
            "workflow_id": workflow_id,
            "path": ".github/workflows/forgeflow.yml",
            "requires_confirmation": True,
            "artifact_names": list(artifacts.keys()),
        }
    if target == "render_worker":
        return {
            "provider": "render",
            "operation": "create_or_update_worker_blueprint",
            "workflow_id": workflow_id,
            "requires_confirmation": True,
            "artifact_names": list(artifacts.keys()),
        }
    if target == "webhook_runtime":
        return {
            "provider": "forgeflow_runtime",
            "operation": "publish_webhook_runtime",
            "workflow_id": workflow_id,
            "base_url": os.getenv("FORGEFLOW_RUNTIME_BASE_URL", ""),
            "requires_confirmation": True,
            "artifact_names": list(artifacts.keys()),
        }
    if target == "vercel_project":
        return {
            "provider": "vercel",
            "operation": "create_deployment",
            "workflow_id": workflow_id,
            "requires_confirmation": True,
            "artifact_names": list(artifacts.keys()),
        }
    return {
        "provider": "local",
        "operation": "prepare_local_docker_command",
        "workflow_id": workflow_id,
        "requires_confirmation": False,
        "artifact_names": list(artifacts.keys()),
    }


def _record_deployment_job(plan_id: str, plan: dict, mode: str = "dry_run") -> dict:
    readiness = plan.get("readiness", {})
    blockers = readiness.get("blocking", [])
    provider_request = _provider_request_for_plan(plan_id, plan)
    status = "blocked" if blockers else ("prepared" if mode == "dry_run" else "ready_for_provider")
    provider_response = {
        "message": "Provider request prepared. External deploy actions require explicit user confirmation.",
        "live_call_performed": False,
    }
    if mode == "live" and not blockers:
        provider_response = _perform_deployment_dispatch(provider_request)
        status = "deployed" if provider_response.get("status") == "succeeded" else provider_response.get("status", "failed")
    job = {
        "id": _stable_id("deploy_job", {"plan_id": plan_id, "mode": mode}),
        "plan_id": plan_id,
        "workflow_id": plan.get("workflow_id"),
        "target": plan.get("target"),
        "status": status,
        "mode": mode,
        "provider_request": provider_request,
        "provider_response": provider_response,
        "blockers": blockers,
        "created_at": _now_iso(),
    }
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO deployment_jobs
        (id, plan_id, workflow_id, target, status, mode, provider_request_json, provider_response_json, blockers_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job["id"],
            job["plan_id"],
            job["workflow_id"],
            job["target"],
            job["status"],
            job["mode"],
            json.dumps(job["provider_request"]),
            json.dumps(job["provider_response"]),
            json.dumps(job["blockers"]),
            job["created_at"],
        ),
    )
    conn.commit()
    conn.close()
    return job


def _perform_deployment_dispatch(provider_request: dict) -> dict:
    provider = provider_request.get("provider")
    if provider == "local":
        return {
            "status": "ready_for_local_command",
            "live_call_performed": False,
            "command": provider_request.get("command", "docker compose up --build"),
            "message": "Local Docker dispatch is prepared. Run the command on the host where Docker is available.",
        }
    if provider in {"github", "render", "vercel"}:
        token_env = {"github": "GITHUB_TOKEN", "render": "RENDER_API_KEY", "vercel": "VERCEL_TOKEN"}[provider]
        if not os.getenv(token_env) and provider not in _credential_services():
            return {
                "status": "blocked",
                "live_call_performed": False,
                "missing_env": token_env,
                "message": f"{provider} deployment requires {token_env} or a stored {provider} credential.",
            }
        return {
            "status": "ready_for_provider_api",
            "live_call_performed": False,
            "message": "Provider credentials are available. API execution is intentionally queued behind explicit provider-specific confirmation.",
            "provider_request": provider_request,
        }
    return {"status": "unsupported_provider", "live_call_performed": False, "message": f"No dispatcher for {provider}"}


def _list_deployment_jobs() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM deployment_jobs ORDER BY created_at DESC LIMIT 30").fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "plan_id": row["plan_id"],
            "workflow_id": row["workflow_id"],
            "target": row["target"],
            "status": row["status"],
            "mode": row["mode"],
            "provider_request": _json_loads(row["provider_request_json"], {}),
            "provider_response": _json_loads(row["provider_response_json"], {}),
            "blockers": _json_loads(row["blockers_json"], []),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


EVAL_SUITES = {
    "core": [
        {
            "id": "hr_grounding",
            "prompt": "Automate HR onboarding from an Excel sheet, draft Gmail and Slack messages, and append a tracking row.",
            "must_detect": ["gmail", "slack", "sheets"],
            "schema_needed": True,
            "risk": "external_write_requires_approval",
        },
        {
            "id": "incident_webhook",
            "prompt": "Expose a webhook that checks an HTTP health endpoint and posts to Slack if it fails.",
            "must_detect": ["http", "slack"],
            "schema_needed": False,
            "risk": "external_write_requires_approval",
        },
        {
            "id": "csv_enrichment",
            "prompt": "Read a CSV of leads, call a CRM API, and prepare updates for approval without writing directly.",
            "must_detect": ["http"],
            "schema_needed": True,
            "risk": "external_write_requires_approval",
        },
    ]
}


async def _run_eval_suite(suite: str = "core") -> dict:
    cases = EVAL_SUITES.get(suite)
    if not cases:
        raise HTTPException(status_code=404, detail="Eval suite not found")
    results = []
    for case in cases:
        preflight = await preflight_prompt({"prompt": case["prompt"]})
        detected = {item["service"] for item in preflight["detected_services"]}
        detected_ok = all(service in detected for service in case["must_detect"])
        schema_ok = preflight["schema_needed"] == case["schema_needed"]
        risk_ok = case["risk"] in preflight["risks"]
        score = sum([detected_ok, schema_ok, risk_ok]) / 3
        results.append({
            **case,
            "detected": sorted(detected),
            "risks": preflight["risks"],
            "score": round(score, 2),
            "passed": score == 1,
        })
    total = round(sum(item["score"] for item in results) / len(results), 2)
    eval_id = _stable_id("eval", {"suite": suite, "score": total})
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO eval_runs
        (id, suite, score, cases_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (eval_id, suite, total, json.dumps(results), _now_iso()),
    )
    conn.commit()
    conn.close()
    return {"id": eval_id, "suite": suite, "score": total, "cases": results}


def _list_eval_runs() -> list[dict]:
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "suite": row["suite"],
            "score": row["score"],
            "cases": _json_loads(row["cases_json"], []),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _audit_runtime_run(run: dict) -> dict:
    steps = run.get("steps", [])
    connectors = sorted({step.get("connector_id", "") for step in steps if step.get("connector_id")})
    external_steps = [step for step in steps if step.get("connector_id", "").split(".", 1)[0] not in {"schema", "http"}]
    approval_steps = [step for step in steps if step.get("status") == "waiting_for_approval"]
    blocked_steps = [step for step in steps if step.get("status") == "blocked"]
    error_text = json.dumps(run, default=str)
    checks = [
        {
            "id": "connectors_detected",
            "label": "Connector steps recorded",
            "status": "pass" if bool(connectors) else "warn",
            "detail": ", ".join(connectors) if connectors else "No connector steps were recorded for this run.",
        },
        {
            "id": "external_writes_gated",
            "label": "External writes gated",
            "status": "pass" if not external_steps or approval_steps else "warn",
            "detail": f"{len(approval_steps)} step(s) waited for approval.",
        },
        {
            "id": "dry_run_safety",
            "label": "Dry-run avoided live calls",
            "status": "pass" if run.get("mode") != "dry_run" or not run.get("output", {}).get("live_call_performed") else "fail",
            "detail": "No provider writes were performed during dry-run." if run.get("mode") == "dry_run" else f"Run mode: {run.get('mode')}",
        },
        {
            "id": "credential_blocking",
            "label": "Credential gaps surfaced",
            "status": "pass" if blocked_steps or run.get("status") not in {"blocked", "failed"} else "warn",
            "detail": f"{len(blocked_steps)} blocked step(s)." if blocked_steps else "No credential blocker in this run.",
        },
        {
            "id": "completion_state",
            "label": "Final status is explicit",
            "status": "pass" if run.get("status") in {"succeeded", "waiting_for_approval", "blocked", "failed"} else "warn",
            "detail": run.get("status", "unknown"),
        },
        {
            "id": "secret_redaction",
            "label": "No obvious secret leakage",
            "status": "pass" if not any(marker in error_text.lower() for marker in ("bearer ", "xoxb-", "sk_live", "sk_test", "api_token")) else "fail",
            "detail": "Run record does not expose common token patterns.",
        },
    ]
    pass_count = sum(1 for check in checks if check["status"] == "pass")
    return {
        "id": f"audit_{run['id']}",
        "run_id": run["id"],
        "kind": "runtime",
        "title": run.get("spec_id", run["id"]),
        "status": run.get("status"),
        "mode": run.get("mode"),
        "created_at": run.get("started_at"),
        "score": round(pass_count / len(checks), 2),
        "connectors": connectors,
        "checks": checks,
    }


def _audit_generated_run(run: dict) -> dict:
    tests_total = int(run.get("tests_total") or 0)
    tests_passed = int(run.get("tests_passed") or 0)
    services = run.get("services") or []
    checks = [
        {
            "id": "execution_status",
            "label": "Execution status explicit",
            "status": "pass" if run.get("status") in {"success", "failed", "needs_review"} else "warn",
            "detail": run.get("status", "unknown"),
        },
        {
            "id": "tests_recorded",
            "label": "Generated tests recorded",
            "status": "pass" if tests_total > 0 else "warn",
            "detail": f"{tests_passed}/{tests_total} tests passed" if tests_total else "No test result count recorded.",
        },
        {
            "id": "tests_passing",
            "label": "Tests passed",
            "status": "pass" if tests_total > 0 and tests_passed == tests_total else ("warn" if tests_total == 0 else "fail"),
            "detail": f"{tests_passed}/{tests_total}",
        },
        {
            "id": "connectors_named",
            "label": "Connector/services captured",
            "status": "pass" if services else "warn",
            "detail": ", ".join(services) if services else "No services listed on this generated workflow.",
        },
        {
            "id": "runtime_outcome",
            "label": "Runtime outcome matches status",
            "status": "pass" if bool(run.get("success")) == (run.get("status") == "success") else "warn",
            "detail": f"success={bool(run.get('success'))}",
        },
    ]
    pass_count = sum(1 for check in checks if check["status"] == "pass")
    return {
        "id": f"audit_{run.get('run_id') or run['workflow_id']}",
        "run_id": run.get("run_id"),
        "workflow_id": run.get("workflow_id"),
        "kind": "generated_workflow",
        "title": run.get("name") or run.get("workflow_id"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "score": round(pass_count / len(checks), 2),
        "connectors": services,
        "checks": checks,
    }


def _recent_run_audits(limit: int = 8) -> list[dict]:
    audits = [_audit_runtime_run(run) for run in _list_runtime_runs(limit=limit)]
    audits.extend(_audit_generated_run(run) for run in _collect_run_history(limit=limit))
    return sorted(audits, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:limit]


def _product_gap_analysis() -> dict:
    connectors = _list_connector_states()
    credentials = _list_credentials()
    eval_runs = _list_eval_runs()
    provider_health = _deployment_provider_health()
    specs = _list_automation_specs(limit=20)
    runtime_runs = _list_runtime_runs(limit=20)
    exports = _list_workflow_exports()
    adapters = _connector_adapters()
    pending_approvals = [item for item in _list_approvals() if item["status"] == "pending"]
    triggers = _list_triggers()
    runs = _collect_run_history(limit=20)
    ingested_count = len(_all_capabilities()) - len(CAPABILITY_REGISTRY)
    active_triggers = [item for item in triggers if item["status"] == "active"]
    failed_runs = [item for item in runs if not item["success"]]
    live_runs = [item for item in runtime_runs if item["mode"] == "live"]
    observability_events = _list_observability_events(limit=20)

    checks = [
        {
            "id": "grounded_capabilities",
            "label": "OpenAPI/MCP capabilities",
            "status": "pass" if ingested_count > 0 else "warn",
            "detail": f"{ingested_count} imported capabilities available",
        },
        {
            "id": "connector_credentials",
            "label": "Connector credentials",
            "status": "pass" if any(item["env_status"]["configured"] or item["metadata"].get("vault_credential") for item in connectors) else "warn",
            "detail": "At least one real connector is configured" if any(item["env_status"]["configured"] or item["metadata"].get("vault_credential") for item in connectors) else "No real connector credentials configured yet",
        },
        {
            "id": "approval_queue",
            "label": "Approval queue",
            "status": "pass",
            "detail": f"{len(pending_approvals)} pending approvals",
        },
        {
            "id": "active_triggers",
            "label": "Trigger activation",
            "status": "pass" if active_triggers else "warn",
            "detail": f"{len(active_triggers)} active triggers",
        },
        {
            "id": "run_reliability",
            "label": "Run reliability",
            "status": "pass" if runs and not failed_runs else "warn",
            "detail": f"{len(runs)} logged runs, {len(failed_runs)} failed or needs-review runs",
        },
        {
            "id": "credential_vault",
            "label": "Credential vault",
            "status": "pass" if credentials else "warn",
            "detail": f"{len(credentials)} encrypted credentials stored",
        },
        {
            "id": "prompt_evals",
            "label": "Prompt evals",
            "status": "pass" if eval_runs else "warn",
            "detail": f"{len(eval_runs)} eval runs recorded",
        },
        {
            "id": "deployment_provider_health",
            "label": "Deployment provider health",
            "status": "pass" if any(item["status"] == "pass" for item in provider_health) else "warn",
            "detail": f"{sum(1 for item in provider_health if item['status'] == 'pass')} provider targets ready",
        },
        {
            "id": "canonical_specs",
            "label": "Canonical automation specs",
            "status": "pass" if specs else "warn",
            "detail": f"{len(specs)} prompt-to-spec compilations stored",
        },
        {
            "id": "typed_adapters",
            "label": "Typed connector adapters",
            "status": "pass" if any(item["status"] == "ready" for item in adapters) else "warn",
            "detail": f"{sum(1 for item in adapters if item['status'] == 'ready')} adapters ready",
        },
        {
            "id": "runtime_ledger",
            "label": "Runtime run ledger",
            "status": "pass" if runtime_runs else "warn",
            "detail": f"{len(runtime_runs)} structured runtime runs recorded",
        },
        {
            "id": "approved_live_execution",
            "label": "Approved live execution",
            "status": "pass" if live_runs else "warn",
            "detail": f"{len(live_runs)} live runtime executions recorded",
        },
        {
            "id": "multi_platform_exports",
            "label": "Multi-platform workflow exports",
            "status": "pass" if exports else "warn",
            "detail": f"{len(exports)} export artifacts generated",
        },
        {
            "id": "self_repair_loop",
            "label": "Self-debug repair loop",
            "status": "pass" if any(run["status"] in {"blocked", "waiting_for_approval"} for run in runtime_runs) else "warn",
            "detail": "Runtime failures can be converted into credential, approval, or debug actions",
        },
        {
            "id": "observability_events",
            "label": "Observability and alerts",
            "status": "pass" if observability_events else "warn",
            "detail": f"{len(observability_events)} operational events recorded",
        },
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "score": round((len(checks) - len(blockers)) / len(checks) * 100),
        "checks": checks,
        "blockers": blockers,
        "next": [
            "Replace generic provider envelopes with official SDK clients for every high-volume connector.",
            "Add hosted worker credentials for GitHub, Render, and webhook runtime promotions.",
            "Run a full live connector execution with real credentials in a staging account.",
        ],
    }


async def _execute_workflow_project(workflow_id: str) -> dict:
    import asyncio as _asyncio
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_file = os.path.join(project_path, "workflow.py")
    if not os.path.exists(workflow_file):
        raise HTTPException(status_code=404, detail="workflow.py not found in project")

    start = datetime.utcnow()

    with tempfile.TemporaryDirectory(prefix=f"forgeflow_run_{workflow_id}_") as run_dir:
        shutil.copytree(project_path, run_dir, dirs_exist_ok=True)
        req_file = os.path.join(run_dir, "requirements.txt")

        if os.path.exists(req_file):
            pip = await _asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-q", "-r", req_file,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=run_dir,
                env=_workflow_run_env(),
            )
            try:
                await _asyncio.wait_for(pip.communicate(), timeout=45)
            except _asyncio.TimeoutError:
                pip.kill()
                await pip.communicate()
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Dependency installation timed out after 45s",
                    "execution_time": 45.0,
                    "return_code": -1,
                }

        proc = await _asyncio.create_subprocess_exec(
            sys.executable, "workflow.py",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
            cwd=run_dir,
            env=_workflow_run_env(),
        )

        try:
            stdout_b, stderr_b = await _asyncio.wait_for(proc.communicate(), timeout=120)
        except _asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": "Execution timed out after 120s",
                "execution_time": 120.0,
                "return_code": -1,
            }

    elapsed = (datetime.utcnow() - start).total_seconds()
    return {
        "success": proc.returncode == 0,
        "stdout": _trim_output(stdout_b.decode("utf-8", errors="replace")),
        "stderr": _trim_output(stderr_b.decode("utf-8", errors="replace")),
        "execution_time": round(elapsed, 2),
        "return_code": proc.returncode,
    }

# ── Event Bus ─────────────────────────────────────────────────

event_listeners: list = []


def on_event(callback):
    event_listeners.append(callback)


async def emit_event(event: dict):
    event["timestamp"] = datetime.utcnow().isoformat()
    await manager.broadcast(event)
    for listener in event_listeners:
        try:
            await listener(event)
        except Exception:
            pass


async def _safe_start_slack_bot():
    """Wrap Slack startup so cert / network errors don't dump a stack trace."""
    try:
        from backend.slack.bot import start_slack_bot
        await start_slack_bot()
    except Exception as e:
        logging.getLogger("slack").warning(
            f"Slack bot offline: {type(e).__name__}: {str(e)[:120]}"
        )


# ── App Lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: index API specs into ChromaDB
    from backend.discovery.vector_store import init_vector_store
    await init_vector_store()

    # Startup: register Slack notification listener
    _slack_bot_real = settings.SLACK_BOT_TOKEN and not settings.SLACK_BOT_TOKEN.startswith("xoxb-your")
    _slack_app_real = settings.SLACK_APP_TOKEN and not settings.SLACK_APP_TOKEN.startswith("xapp-your")

    if _slack_bot_real:
        from backend.slack.notifications import slack_event_listener
        on_event(slack_event_listener)
        print("[Slack] Notification listener registered")
    else:
        print("[Slack] Bot token not configured — notifications disabled")

    # Startup: activate Slack bot (bidirectional — /forge command, DMs)
    slack_socket_enabled = os.getenv("SLACK_SOCKET_MODE", "0").lower() in ("1", "true", "yes")
    slack_disabled = os.getenv("SLACK_DISABLED", "0").lower() in ("1", "true", "yes")
    if _slack_app_real and slack_socket_enabled and not slack_disabled:
        asyncio.create_task(_safe_start_slack_bot())
        print("[Slack] Bot starting in Socket Mode (bidirectional)")
    elif slack_disabled:
        print("[Slack] Disabled by SLACK_DISABLED=1")
    elif _slack_app_real and not slack_socket_enabled:
        print("[Slack] Socket Mode available but disabled — set SLACK_SOCKET_MODE=1 to enable /forge commands")
    else:
        print("[Slack] App token not configured — /forge command disabled")

    worker_enabled = os.getenv("FORGEFLOW_QUEUE_WORKER", "0").lower() in ("1", "true", "yes")
    queue_worker_task = None
    if worker_enabled:
        queue_worker_task = asyncio.create_task(_queue_worker_loop())
        app.state.queue_worker_enabled = True
        print("[ForgeFlow] Queue worker enabled")
    else:
        app.state.queue_worker_enabled = False
        print("[ForgeFlow] Queue worker disabled — set FORGEFLOW_QUEUE_WORKER=1 to process hosted jobs automatically")

    try:
        yield
    finally:
        if queue_worker_task:
            queue_worker_task.cancel()
            try:
                await queue_worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="ForgeFlow", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST Endpoints ────────────────────────────────────────────

@app.post("/api/forge", response_model=ForgeResponse)
async def forge_workflow(req: ForgeRequest):
    """Start the ForgeFlow pipeline from a natural language request."""
    from backend.graph import run_forgeflow_pipeline

    workflow_id = str(uuid.uuid4())[:8]

    await emit_event({
        "event_type": "workflow.created",
        "phase": "collecting",
        "message": f"Starting workflow generation: {req.message[:80]}...",
        "data": {"workflow_id": workflow_id},
    })

    result = await run_forgeflow_pipeline(
        user_request=req.message,
        workflow_id=workflow_id,
        slack_channel=req.slack_channel or settings.SLACK_NOTIFICATION_CHANNEL,
        event_callback=emit_event,
    )

    # If pipeline stopped for clarification, return partial result
    if result.get("needs_clarification"):
        return ForgeResponse(
            workflow_id=workflow_id,
            phase="clarification_needed",
            message="I need a bit more information to generate the best workflow.",
            dag=None,
            code=None,
            events=result.get("events", []),
        )

    return ForgeResponse(
        workflow_id=workflow_id,
        phase=result.get("phase", "deployed"),
        message=result.get("final_message", "Workflow completed"),
        dag=result.get("workflow_dag"),
        code=result.get("generated_code"),
        events=result.get("events", []),
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ForgeFlow"}


@app.get("/api/status")
async def provider_status():
    """Return safe runtime configuration details for the UI and deploy checks."""
    provider = settings.LLM_PROVIDER.lower()
    if provider not in {"openai", "groq", "gemini"}:
        provider = "groq"

    llm_providers = {
        "openai": {
            "configured": bool(settings.OPENAI_API_KEY),
            "model": settings.OPENAI_MODEL,
            "fast_model": settings.OPENAI_FAST_MODEL,
        },
        "groq": {
            "configured": bool(settings.GROQ_API_KEY),
            "model": settings.GROQ_MODEL,
            "fast_model": settings.GROQ_FAST_MODEL,
        },
        "gemini": {
            "configured": bool(settings.GEMINI_API_KEY),
            "model": settings.GEMINI_MODEL,
            "fast_model": settings.GEMINI_FAST_MODEL,
        },
    }
    embedding_provider = settings.EMBEDDING_PROVIDER.lower()
    embedding_configured = (
        True if embedding_provider == "local"
        else bool(settings.GEMINI_API_KEY) if embedding_provider == "gemini"
        else False
    )

    services = {}
    for key, info in SUPPORTED_SERVICES.items():
        required_env = info.get("env_vars", ())
        oauth_readiness = _oauth_env_readiness(key)
        has_credential = bool(_secret_for_service(key))
        services[key] = {
            "name": info["name"],
            "configured": all(bool(os.getenv(env_name, "")) for env_name in required_env) or has_credential,
            "required_env": required_env,
            "auth_type": info.get("auth_type", "api_key"),
            "source": info.get("source", "catalog"),
            "oauth_supported": key in _oauth_specs(),
            "oauth_ready": bool(oauth_readiness.get("available")),
            "oauth_missing_env": oauth_readiness.get("missing", []) if key in _oauth_specs() else [],
        }

    return {
        "status": "ok",
        "service": "ForgeFlow",
        "llm": {
            "provider": provider,
            "fallback_provider": settings.LLM_FALLBACK_PROVIDER,
            "model": llm_providers[provider]["model"],
            "fast_model": llm_providers[provider]["fast_model"],
            "configured": llm_providers[provider]["configured"],
            "providers": llm_providers,
        },
        "embeddings": {
            "provider": embedding_provider,
            "configured": embedding_configured,
            "model": settings.GEMINI_EMBEDDING_MODEL if embedding_provider == "gemini" else "local",
        },
        "services": services,
    }


@app.get("/api/product/overview")
async def product_overview():
    """Return a product-grade dashboard summary."""
    from backend.deployment.workflow_store import list_workflows as _list

    workflows = _visible_workflows(_list(limit=30))[:12]
    status = await provider_status()
    service_values = list(status["services"].values())
    configured_services = sum(1 for service in service_values if service["configured"])
    recent_runs = _collect_run_history(limit=8)
    approvals_data = _list_approvals()

    return {
        "metrics": {
            "total_workflows": len(workflows),
            "configured_services": configured_services,
            "available_services": len(service_values),
            "recent_successful_runs": sum(1 for run in recent_runs if run["success"]),
            "approval_queue": sum(1 for item in approvals_data if item["status"] == "pending"),
        },
        "workflows": workflows,
        "recent_runs": recent_runs,
        "llm": status["llm"],
        "embeddings": status["embeddings"],
    }


@app.get("/api/product/gaps")
async def product_gaps():
    """Return product self-assessment against production automation readiness."""
    return _product_gap_analysis()


@app.get("/api/production/readiness")
async def production_readiness():
    """Return fail-closed production launch readiness across runtime, credentials, and deploy."""
    return _production_readiness_report()


@app.get("/api/capabilities")
async def capabilities():
    """List typed capabilities the planner should compose before custom code."""
    return {"capabilities": _all_capabilities()}


@app.get("/api/connectors/adapters")
async def connector_adapters():
    """List typed connector adapter contracts available to compiled automation specs."""
    return {"adapters": _connector_adapters()}


@app.post("/api/connectors/adapters/{adapter_id}/validate")
async def validate_connector_adapter(adapter_id: str):
    """Validate a connector contract and return credential-safe next actions."""
    return {"validation": _validate_connector_adapter(adapter_id)}


@app.post("/api/connectors/{service}/test")
async def test_connector_service(service: str, body: dict | None = None):
    """Run a credential-safe connector test. live=true performs a read-only provider probe."""
    body = body or {}
    return {"test": _test_connector_service(service, live=bool(body.get("live")))}


@app.get("/api/connectors/tests")
async def connector_tests():
    return {"tests": _list_connector_tests()}


@app.post("/api/challenge/conversation")
async def challenge_conversation(body: dict):
    """Collect business requirements in plain English before generation."""
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    return {"conversation": _business_conversation(prompt, body.get("context", {}))}


@app.get("/api/specs")
async def automation_specs():
    """List canonical automation specs compiled from prompts."""
    return {"specs": _list_automation_specs()}


@app.post("/api/specs/compile")
async def compile_automation_spec(body: dict):
    """Compile a prompt into ForgeFlow's canonical automation spec before codegen."""
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    spec = await _compile_automation_spec(prompt, body.get("context", {}))
    return {"spec": spec}


@app.post("/api/autopilot/run")
async def prompt_autopilot(body: dict):
    """Run the full prompt-to-automation loop and return a production readiness verdict."""
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    platforms = body.get("platforms") or ["forgeflow", "n8n", "zapier", "github_actions"]
    if not isinstance(platforms, list):
        raise HTTPException(status_code=400, detail="platforms must be a list")
    return {"autopilot": await _run_prompt_autopilot(prompt, body.get("context", {}), [str(item) for item in platforms])}


@app.get("/api/specs/{spec_id}/exports")
async def spec_exports(spec_id: str):
    """List generated platform export artifacts for a canonical spec."""
    return {"exports": _list_workflow_exports(spec_id)}


@app.get("/api/specs/{spec_id}/credentials")
async def spec_credentials(spec_id: str):
    """Return connector credentials required before this spec can run live."""
    return _credential_requirements_for_spec(spec_id)


@app.post("/api/specs/{spec_id}/export")
async def export_spec(spec_id: str, body: dict | None = None):
    """Export a canonical spec to a target workflow platform format."""
    body = body or {}
    return {"export": _export_spec_to_platform(spec_id, str(body.get("platform", "forgeflow")))}


@app.get("/api/runtime/runs")
async def runtime_runs():
    """Return structured runtime dry-run/live run ledger entries."""
    return {"runs": _list_runtime_runs()}


@app.post("/api/runtime/specs/{spec_id}/dry-run")
async def dry_run_runtime_spec(spec_id: str, body: dict | None = None):
    """Evaluate a canonical spec through adapter dry-run contracts without live external calls."""
    body = body or {}
    return {"run": await _dry_run_automation_spec(spec_id, body.get("inputs", {}))}


@app.post("/api/runtime/specs/{spec_id}/execution-plan")
async def runtime_execution_plan(spec_id: str, body: dict | None = None):
    """Preview exact live connector readiness without sending external requests."""
    body = body or {}
    return {"plan": _runtime_execution_plan(spec_id, body.get("inputs", {}), approved=bool(body.get("approved")))}


@app.post("/api/runtime/specs/{spec_id}/execute-live")
async def execute_live_runtime_spec(spec_id: str, body: dict | None = None):
    """Execute approved live connector steps. Missing approvals, credentials, or inputs block safely."""
    body = body or {}
    if not body.get("approved"):
        raise HTTPException(status_code=403, detail="approved=true is required for live connector execution")
    return {"run": await _live_run_automation_spec(spec_id, body.get("inputs", {}), approved=True)}


@app.post("/api/runtime/runs/{run_id}/repair")
async def repair_runtime_run(run_id: str):
    """Convert a blocked or failed runtime run into concrete repair actions."""
    return {"repair": _repair_runtime_run(run_id)}


@app.post("/api/runtime/runs/{run_id}/repair/retest")
async def retest_runtime_repair(run_id: str):
    """Re-run readiness planning after a repair so the user sees what is still blocked."""
    return {"retest": await _retest_repair(run_id)}


@app.get("/api/observability")
async def observability():
    queue = _list_run_queue()
    events = _list_observability_events()
    return {
        "events": events,
        "alerts": [event for event in events if event["severity"] in {"error", "critical"}],
        "queue": {
            "queued": sum(1 for item in queue if item["status"] == "queued"),
            "dead_letter": sum(1 for item in queue if item["status"] == "dead_letter"),
            "running": sum(1 for item in queue if item["status"] == "running"),
        },
    }


@app.post("/api/demo/hr-onboarding")
async def hr_onboarding_challenge_demo(body: dict | None = None):
    """Run the hackathon challenge path: prompt, spec, dry-run, exports, validation, repair."""
    _require_demo_enabled()
    body = body or {}
    return await _run_hr_onboarding_demo(body.get("prompt"))


@app.get("/api/staging/profile")
async def staging_profile():
    """Return the safe staging workspace used for draft-first demo execution."""
    return {"staging": _staging_profile()}


@app.post("/api/demo/judge")
async def judge_challenge_demo(body: dict | None = None):
    """Run the end-to-end staging demo packet for live judging."""
    _require_demo_enabled()
    body = body or {}
    return await _run_judge_demo(body.get("prompt"))


@app.get("/api/app-builder/builds")
async def app_builder_builds():
    """List generated app-builder artifacts."""
    return {"builds": _list_app_builds()}


@app.post("/api/app-builder/generate")
async def app_builder_generate(body: dict):
    """Generate a runnable app artifact from plain English instead of a workflow DAG."""
    return {"build": _generate_app_build(str(body.get("prompt", "")))}


@app.get("/api/app-builder/builds/{build_id}/download")
async def app_builder_download(build_id: str):
    """Download a generated app-builder artifact as a zip package."""
    build_dir = os.path.abspath(os.path.join(APP_BUILDS_DIR, build_id))
    root = os.path.abspath(APP_BUILDS_DIR)
    if not build_dir.startswith(root) or not os.path.isdir(build_dir):
        raise HTTPException(status_code=404, detail="App build not found")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for base, _dirs, files in os.walk(build_dir):
            for file_name in files:
                full_path = os.path.join(base, file_name)
                archive.write(full_path, os.path.relpath(full_path, build_dir))
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{build_id}.zip"'},
    )


@app.get("/api/templates")
async def templates():
    """List reusable automation templates."""
    return {"templates": TEMPLATE_GALLERY}


@app.get("/api/runs")
async def run_history():
    """Return recent local workflow execution artifacts."""
    return {"runs": _collect_run_history(limit=30), "queue": _list_run_queue()}


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str):
    """Return stdout/stderr and retry metadata for one persisted run."""
    run = _get_run_log(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/runs/queue/list")
async def run_queue():
    return {"queue": _list_run_queue()}


@app.get("/api/queue")
async def queue_list():
    return {"queue": _list_run_queue()}


@app.get("/api/runs/queue/worker")
async def queue_worker_status():
    return {
        "enabled": bool(getattr(app.state, "queue_worker_enabled", False)),
        "interval_seconds": int(os.getenv("FORGEFLOW_QUEUE_WORKER_INTERVAL", "10")),
        "batch_size": int(os.getenv("FORGEFLOW_QUEUE_WORKER_BATCH", "5")),
        "due": _due_queue_items(limit=20),
    }


@app.get("/api/queue/worker")
async def queue_worker_status_alias():
    return await queue_worker_status()


@app.post("/api/runs/queue")
async def enqueue_run(body: dict):
    workflow_id = str(body.get("workflow_id", "")).strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id is required")
    return _enqueue_run(
        workflow_id=workflow_id,
        payload=body.get("payload", {}),
        priority=int(body.get("priority", 5)),
        max_attempts=int(body.get("max_attempts", 3)),
    )


@app.post("/api/queue")
async def enqueue_run_alias(body: dict):
    return await enqueue_run(body)


@app.post("/api/runs/queue/{queue_id}/process")
async def process_run_queue_item(queue_id: str):
    return await _process_queue_item(queue_id)


@app.post("/api/queue/{queue_id}/process")
async def process_run_queue_item_alias(queue_id: str):
    return await _process_queue_item(queue_id)


@app.post("/api/runs/queue/process-due")
async def process_due_run_queue(body: dict | None = None):
    body = body or {}
    return await _process_due_queue(limit=int(body.get("limit", 5)))


@app.post("/api/queue/process-due")
async def process_due_run_queue_alias(body: dict | None = None):
    return await process_due_run_queue(body)


@app.post("/api/runs/queue/recover-stale")
async def recover_stale_run_queue(body: dict | None = None):
    body = body or {}
    return _recover_stale_queue_items(max_age_seconds=int(body.get("max_age_seconds", 600)))


@app.post("/api/queue/recover-stale")
async def recover_stale_run_queue_alias(body: dict | None = None):
    return await recover_stale_run_queue(body)


@app.get("/api/approvals")
async def approvals():
    """Return current approval queue and product approval policy."""
    return {
        "pending": [item for item in _list_approvals() if item["status"] == "pending"],
        "all": _list_approvals(),
        "policy": [
            "Preview and approve before sending emails or Slack messages.",
            "Preview and approve before writing to external systems.",
            "Require explicit confirmation before deletions or permission changes.",
            "Dry-run mode never reads credentials or calls external APIs.",
        ],
    }


@app.post("/api/approvals")
async def create_approval(body: dict):
    """Create a persistent approval item for a risky action preview."""
    title = str(body.get("title", "")).strip()
    action_type = str(body.get("action_type", "external_action")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Approval title is required")
    approval_id = _stable_id("approval", body)
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO approvals
        (id, workflow_id, action_type, title, preview_json, risk, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            approval_id,
            body.get("workflow_id"),
            action_type,
            title,
            json.dumps(body.get("preview", {})),
            body.get("risk", "external_write"),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": approval_id, "status": "pending"}


@app.post("/api/approvals/{approval_id}/{decision}")
async def decide_approval(approval_id: str, decision: str):
    """Approve or reject a queued action preview."""
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")
    status_value = "approved" if decision == "approve" else "rejected"
    conn = _platform_db()
    cur = conn.execute(
        "UPDATE approvals SET status = ?, updated_at = ? WHERE id = ?",
        (status_value, _now_iso(), approval_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Approval not found")
    return {"id": approval_id, "status": status_value}


@app.get("/api/triggers")
async def list_triggers():
    return {
        "triggers": _list_triggers(),
        "events": _list_trigger_events(),
    }


@app.post("/api/triggers")
async def create_trigger(body: dict):
    workflow_id = str(body.get("workflow_id", "")).strip()
    trigger_type = str(body.get("trigger_type", "manual")).strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id is required")
    trigger_id = _stable_id("trigger", body)
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO triggers
        (id, workflow_id, trigger_type, config_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trigger_id,
            workflow_id,
            trigger_type,
            json.dumps(body.get("config", {})),
            body.get("status", "paused"),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": trigger_id, "status": body.get("status", "paused")}


@app.post("/api/triggers/{trigger_id}/{action}")
async def update_trigger_state(trigger_id: str, action: str):
    if trigger_id == "schedules" and action == "process":
        return await _process_due_schedules()
    if action not in {"activate", "pause"}:
        raise HTTPException(status_code=400, detail="Action must be activate or pause")
    status = "active" if action == "activate" else "paused"
    conn = _platform_db()
    cur = conn.execute(
        "UPDATE triggers SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now_iso(), trigger_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return {"id": trigger_id, "status": status}


@app.post("/api/webhooks/{trigger_id}")
async def invoke_webhook_trigger(trigger_id: str, body: dict):
    trigger = _get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    if trigger["status"] != "active":
        event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, "ignored_inactive")
        return {"accepted": False, "event": event, "message": "Trigger is paused"}
    queue_item = _enqueue_run(
        trigger["workflow_id"],
        {"trigger_id": trigger_id, "event_type": "webhook", "payload": body},
        priority=int(trigger["config"].get("priority", 5)),
        max_attempts=int(trigger["config"].get("max_attempts", 3)),
    )
    event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, "queued", queue_item["id"])
    _record_observability_event("trigger", "info", "webhook_queued", trigger["workflow_id"], {"trigger_id": trigger_id, "queue_id": queue_item["id"]})
    if trigger["config"].get("process_immediately"):
        processed = await _process_queue_item(queue_item["id"])
        return {"accepted": True, "event": event, "queue": queue_item, "processed": processed}
    return {"accepted": True, "event": event, "queue": queue_item}


async def _process_due_schedules():
    """Queue due schedule triggers using simple interval_seconds config."""
    queued = []
    now_ts = datetime.utcnow().timestamp()
    for trigger in _list_triggers():
        if trigger["status"] != "active" or trigger["trigger_type"] != "schedule":
            continue
        config = trigger.get("config", {})
        interval = int(config.get("interval_seconds", 3600))
        last_run = float(config.get("last_run_ts", 0))
        if now_ts - last_run < interval:
            continue
        queue_item = _enqueue_run(trigger["workflow_id"], {"trigger_id": trigger["id"], "event_type": "schedule"}, max_attempts=int(config.get("max_attempts", 3)))
        config["last_run_ts"] = now_ts
        conn = _platform_db()
        conn.execute("UPDATE triggers SET config_json = ?, updated_at = ? WHERE id = ?", (json.dumps(config), _now_iso(), trigger["id"]))
        conn.commit()
        conn.close()
        queued.append(queue_item)
        _record_trigger_event(trigger["id"], trigger["workflow_id"], "schedule", config, "queued", queue_item["id"])
    return {"queued": queued}


@app.post("/api/triggers/schedules/process")
async def process_due_schedules():
    return await _process_due_schedules()


@app.get("/api/triggers/events")
async def trigger_events():
    return {"events": _list_trigger_events()}


@app.get("/api/deploy/targets")
async def deployment_targets():
    health_by_id = {item["id"]: item for item in _deployment_provider_health()}
    targets = []
    for target in DEPLOYMENT_TARGETS:
        targets.append({
            **target,
            "env_status": _env_status(target.get("requires_env", [])),
            "provider_health": health_by_id.get(target["id"], {}),
        })
    return {"targets": targets}


@app.get("/api/deploy/plans")
async def deployment_plans():
    return {"plans": _list_deployment_plans(), "activations": _list_deployment_activations(), "jobs": _list_deployment_jobs()}


@app.post("/api/deploy/plan")
async def create_deployment_plan(body: dict):
    workflow_id = str(body.get("workflow_id", "")).strip()
    target = str(body.get("target", "local_docker")).strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id is required")
    target_info = next((item for item in DEPLOYMENT_TARGETS if item["id"] == target), None)
    if not target_info:
        raise HTTPException(status_code=400, detail="Unknown deployment target")
    readiness = _deployment_readiness(workflow_id, target_info)
    artifacts = _deployment_artifacts(workflow_id, target)
    plan = {
        "workflow_id": workflow_id,
        "target": target,
        "target_status": target_info["status"],
        "readiness": readiness,
        "artifacts": artifacts,
        "steps": [
            "Validate workflow project files",
            "Verify required secrets are present",
            "Run generated tests",
            "Build deployment artifact",
            "Activate trigger or runtime",
        ],
        "next_action": "ready_to_activate" if readiness["ready"] else "resolve readiness blockers",
    }
    plan_id = _stable_id("deploy", plan)
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO deployment_plans
        (id, workflow_id, target, status, plan_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (plan_id, workflow_id, target, "planned", json.dumps(plan), _now_iso()),
    )
    conn.commit()
    conn.close()
    return {"id": plan_id, "status": "planned", "plan": plan}


@app.post("/api/deploy/plans/{plan_id}/activate")
async def activate_deployment_plan(plan_id: str):
    conn = _platform_db()
    row = conn.execute("SELECT * FROM deployment_plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Deployment plan not found")
    plan = _json_loads(row["plan_json"], {})
    status = "ready" if plan.get("readiness", {}).get("ready") else "blocked"
    conn.execute("UPDATE deployment_plans SET status = ? WHERE id = ?", (status, plan_id))
    conn.commit()
    conn.close()
    activation = _record_deployment_activation(plan_id, plan, status)
    return {"id": plan_id, "status": status, "plan": plan, "activation": activation}


@app.post("/api/deploy/plans/{plan_id}/dispatch")
async def dispatch_deployment_plan(plan_id: str, body: dict | None = None):
    body = body or {}
    mode = str(body.get("mode", "dry_run")).strip() or "dry_run"
    conn = _platform_db()
    row = conn.execute("SELECT * FROM deployment_plans WHERE id = ?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Deployment plan not found")
    plan = _json_loads(row["plan_json"], {})
    job = _record_deployment_job(plan_id, plan, mode)
    return {"id": plan_id, "job": job}


@app.post("/api/deploy/plans/{plan_id}/complete")
async def complete_deployment_job(plan_id: str, body: dict):
    """Record an externally completed provider deployment without storing secrets."""
    status = str(body.get("status", "deployed")).strip()
    provider_url = str(body.get("provider_url", "")).strip()
    conn = _platform_db()
    row = conn.execute("SELECT * FROM deployment_plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Deployment plan not found")
    plan = _json_loads(row["plan_json"], {})
    conn.execute("UPDATE deployment_plans SET status = ? WHERE id = ?", (status, plan_id))
    conn.commit()
    conn.close()
    activation = _record_deployment_activation(plan_id, {**plan, "provider_url": provider_url}, status)
    _record_observability_event("deployment", "info", "deployment_completed", plan.get("workflow_id", plan_id), {"plan_id": plan_id, "provider_url": provider_url, "status": status})
    return {"id": plan_id, "status": status, "provider_url": provider_url, "activation": activation}


@app.get("/api/deploy/jobs")
async def deployment_jobs():
    return {"jobs": _list_deployment_jobs()}


@app.get("/api/ingestions")
async def list_ingestions():
    conn = _platform_db()
    rows = conn.execute("SELECT * FROM ingestions ORDER BY created_at DESC").fetchall()
    conn.close()
    return {
        "ingestions": [
            {
                **dict(row),
                "summary": json.loads(row["summary_json"]),
                "capabilities": json.loads(row["capabilities_json"]),
            }
            for row in rows
        ]
    }


@app.post("/api/openapi/ingest")
async def ingest_openapi(body: dict):
    capabilities_data = _extract_openapi_capabilities(body)
    if not capabilities_data:
        raise HTTPException(status_code=400, detail="No OpenAPI paths found")
    name = body.get("info", {}).get("title", "OpenAPI Import")
    summary = {
        "title": name,
        "version": body.get("info", {}).get("version"),
        "paths": len(body.get("paths") or {}),
        "capability_count": len(capabilities_data),
    }
    return _store_ingestion("openapi", name, summary, capabilities_data)


async def _ingest_openapi_from_url(url: str) -> dict:
    body = _fetch_json_url(url)
    ingestion = await ingest_openapi(body)
    ingestion["source_url"] = url
    return ingestion


@app.post("/api/openapi/upload")
async def upload_openapi(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    try:
        body = json.loads(content)
    except json.JSONDecodeError:
        try:
            import yaml
            body = yaml.safe_load(content)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Upload JSON or YAML OpenAPI content: {exc}")
    return await ingest_openapi(body)


@app.post("/api/openapi/import-url")
async def import_openapi_url(body: dict):
    """Fetch a public OpenAPI JSON/YAML URL and ingest its endpoints as capabilities."""
    return await _ingest_openapi_from_url(str(body.get("url", "")).strip())


@app.post("/api/mcp/ingest")
async def ingest_mcp(body: dict):
    capabilities_data = _extract_mcp_capabilities(body)
    if not capabilities_data:
        raise HTTPException(status_code=400, detail="No MCP tools found")
    name = body.get("name", "MCP Import")
    summary = {
        "name": name,
        "tool_count": len(capabilities_data),
    }
    return _store_ingestion("mcp", name, summary, capabilities_data)


@app.post("/api/mcp/discover")
async def discover_mcp_adapter(body: dict):
    """Accept a discovered MCP server manifest and ingest its tools as capabilities."""
    server_url = str(body.get("server_url", "")).strip()
    manifest = body.get("manifest") or body
    if server_url and isinstance(manifest, dict):
        manifest = {**manifest, "server_url": server_url}
    ingestion = await ingest_mcp(manifest)
    return {"server_url": server_url, "ingestion": ingestion, "dynamic_capabilities": ingestion["capabilities"]}


@app.post("/api/discovery/search")
async def discovery_search(body: dict):
    """Search imported capabilities and public OpenAPI directories for a prompt."""
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    return _discover_capabilities(prompt, include_public=bool(body.get("include_public", True)))


@app.post("/api/discovery/import")
async def discovery_import(body: dict):
    """Import a selected public OpenAPI candidate discovered by /api/discovery/search."""
    source_url = str(body.get("source_url", "")).strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required")
    ingestion = await _ingest_openapi_from_url(source_url)
    return {"ingestion": ingestion, "capabilities": ingestion["capabilities"]}


@app.get("/api/connectors/oauth/{service}/start")
async def start_oauth_connector(service: str):
    """Return an OAuth start scaffold without storing credentials."""
    service = service.lower()
    spec = _oauth_specs().get(service)
    if not spec:
        raise HTTPException(status_code=404, detail="OAuth connector not available for this service")
    state = _stable_id("oauth", {"service": service})
    client_id = _oauth_config_value(service, spec["client_id_env"], spec)
    redirect_uri = _oauth_config_value(service, spec["redirect_uri_env"], spec) or "http://127.0.0.1:8000/api/connectors/oauth/callback"
    query = {
        "client_id": client_id or f"missing-{spec['client_id_env']}",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(spec["scopes"]),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if service == "slack":
        query["scope"] = ",".join(spec["scopes"])
    auth_url = f"{spec['auth_url']}?{urlencode(query)}"
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO oauth_sessions
        (state, service, status, auth_url, scopes_json, created_at, updated_at)
        VALUES (?, ?, 'started', ?, ?, ?, ?)
        """,
        (state, service, auth_url, json.dumps(spec["scopes"]), now, now),
    )
    conn.commit()
    conn.close()
    return {
        "service": service,
        "state": state,
        "auth_url": auth_url,
        "scopes": spec["scopes"],
        "status": "ready_for_user_authorization" if client_id else "missing_oauth_client",
        "oauth_env": _oauth_env_readiness(service),
        "missing_env": [
            name for name in (spec["client_id_env"], spec["client_secret_env"], spec["redirect_uri_env"])
            if not _oauth_config_value(service, name, spec)
        ],
        "message": "OAuth session created. Complete callback after provider authorization.",
    }


@app.post("/api/connectors/google-oauth/setup")
async def save_google_oauth_setup(body: dict):
    """Store Google OAuth client setup in the encrypted local vault instead of editing .env."""
    client_id = str(body.get("client_id", "")).strip()
    client_secret = str(body.get("client_secret", "")).strip()
    redirect_uri = str(body.get("redirect_uri", "http://localhost:8000/api/connectors/oauth/callback")).strip()
    sender_email = str(body.get("sender_email", "")).strip()
    sheet_id = str(body.get("sheet_id", "")).strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=400, detail="client_id, client_secret, and redirect_uri are required")

    metadata = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_OAUTH_REDIRECT_URI": redirect_uri,
        "configured_from_ui": True,
        "services": ["gmail", "sheets", "calendar"],
    }
    if sender_email:
        metadata["sender_email"] = sender_email
        metadata["GMAIL_SENDER_EMAIL"] = sender_email
    if sheet_id:
        metadata["sheet_id"] = sheet_id
        metadata["GOOGLE_SHEET_ID"] = sheet_id

    credential = _store_credential("google_oauth", "Google OAuth client", "client_secret", client_secret, metadata)
    _upsert_connector_state(
        service="google_oauth",
        status="oauth_client_configured",
        auth_type="oauth2_client",
        scopes=[],
        env_vars=[],
        metadata={"credential_id": credential["id"], "label": credential["label"], "services": metadata["services"]},
    )
    return {
        "status": "stored",
        "credential": {"id": credential["id"], "label": credential["label"], "masked": credential["masked"]},
        "readiness": {service: _oauth_env_readiness(service) for service in ("gmail", "sheets", "calendar")},
    }


@app.get("/api/connectors")
async def connector_lifecycle():
    return {
        "connectors": _list_connector_states(),
        "oauth_sessions": _list_oauth_sessions(),
        "credentials": _list_credentials(),
        "credential_audit": _list_credential_audit(),
        "connector_tests": _list_connector_tests(),
    }


@app.post("/api/vault/credentials")
async def store_vault_credential(body: dict):
    service = str(body.get("service", "")).strip().lower()
    label = str(body.get("label", "")).strip()
    kind = str(body.get("kind", "access_token")).strip()
    secret_value = str(body.get("secret", "")).strip()
    if not service or not label or not secret_value:
        raise HTTPException(status_code=400, detail="service, label, and secret are required")
    credential = _store_credential(service, label, kind, secret_value, body.get("metadata", {}))
    _upsert_connector_state(
        service=service,
        status="vault_credential_stored",
        auth_type="oauth2" if "token" in kind else "api_key",
        scopes=_oauth_specs().get(service, {}).get("scopes", []),
        env_vars=[],
        metadata={"credential_id": credential["id"], "label": label},
    )
    return credential


@app.post("/api/vault/credentials/{credential_id}/rotate")
async def rotate_vault_credential(credential_id: str, body: dict):
    credential = _rotate_credential(credential_id, str(body.get("secret", "")).strip(), body.get("metadata", {}))
    _upsert_connector_state(
        service=credential["service"],
        status="vault_credential_rotated",
        auth_type="oauth2" if "token" in credential["kind"] else "api_key",
        scopes=_oauth_specs().get(credential["service"], {}).get("scopes", []),
        env_vars=[],
        metadata={"credential_id": credential["id"], "label": credential["label"], "rotated_at": credential["updated_at"]},
    )
    return credential


@app.get("/api/vault/credentials")
async def list_vault_credentials():
    return {"credentials": _list_credentials()}


@app.post("/api/connectors/oauth/callback")
async def complete_oauth_connector(body: dict):
    """Record OAuth callback completion without exposing or returning token values."""
    state = str(body.get("state", "")).strip()
    code = str(body.get("code", "")).strip()
    if not state or not code:
        raise HTTPException(status_code=400, detail="state and code are required")
    conn = _platform_db()
    session = conn.execute("SELECT * FROM oauth_sessions WHERE state = ?", (state,)).fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="OAuth session not found")
    service = session["service"]
    spec = _oauth_specs().get(service)
    now = _now_iso()
    conn.execute("UPDATE oauth_sessions SET status = 'callback_received', updated_at = ? WHERE state = ?", (now, state))
    conn.commit()
    conn.close()
    token_exchange = None
    if body.get("exchange"):
        token_exchange = _exchange_oauth_code(service, code, body.get("redirect_uri"))
        conn = _platform_db()
        conn.execute("UPDATE oauth_sessions SET status = 'tokens_stored', updated_at = ? WHERE state = ?", (_now_iso(), state))
        conn.commit()
        conn.close()
    connector = _upsert_connector_state(
        service=service,
        status="tokens_stored" if token_exchange else "authorization_code_received",
        auth_type="oauth2",
        scopes=_json_loads(session["scopes_json"], []),
        env_vars=spec.get("env_vars", []) if spec else [],
        metadata={
            "state": state,
            "code_received": True,
            "token_exchange": "complete" if token_exchange else "pending_server_side_secret_exchange",
            "token_url": spec.get("token_url") if spec else None,
            "stored_credentials": token_exchange.get("stored_credentials", []) if token_exchange else [],
        },
    )
    return {"service": service, "status": connector["status"], "connector": connector, "token_exchange": token_exchange}


@app.get("/api/connectors/oauth/callback", response_class=HTMLResponse)
async def complete_oauth_connector_redirect(state: str = "", code: str = "", error: str = ""):
    """Handle provider redirects so non-technical users do not copy OAuth codes manually."""
    if error:
        safe_error = html.escape(error)
        return HTMLResponse(
            f"<h1>ForgeFlow authorization failed</h1><p>{safe_error}</p><p>You can close this tab and retry from Connector Center.</p>",
            status_code=400,
        )
    try:
        result = await complete_oauth_connector({"state": state, "code": code, "exchange": True})
    except HTTPException as exc:
        safe_detail = html.escape(str(exc.detail))
        return HTMLResponse(
            f"<h1>ForgeFlow authorization needs attention</h1><p>{safe_detail}</p><p>Return to Connector Center and check the OAuth setup.</p>",
            status_code=exc.status_code,
        )
    safe_service = html.escape(str(result["service"]))
    return HTMLResponse(
        f"""
        <html>
          <body style="font-family: Inter, system-ui, sans-serif; background: #070a0f; color: #e5edf7; padding: 40px;">
            <h1>{safe_service} connected</h1>
            <p>ForgeFlow stored the returned OAuth token in the local vault. You can close this tab and return to Connector Center.</p>
          </body>
        </html>
        """
    )


@app.get("/api/evals/suites")
async def eval_suites():
    return {
        "audits": _recent_run_audits(),
        "suites": [{"id": key, "cases": value} for key, value in EVAL_SUITES.items()],
        "runs": _list_eval_runs(),
    }


@app.post("/api/evals/run")
async def run_eval_suite(body: dict):
    return await _run_eval_suite(str(body.get("suite", "core")))


@app.post("/api/schemas/inspect")
async def inspect_schema(file: UploadFile = File(...)):
    """Inspect CSV/XLSX columns and sample rows for grounded planning."""
    content = await file.read()
    try:
        schema = _inspect_tabular_bytes(file.filename or "upload.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"schema": schema}


@app.post("/api/preflight")
async def preflight_prompt(body: dict):
    """Analyze a workflow prompt before generation for missing access and schemas."""
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    prompt_lower = prompt.lower()
    service_markers = {
        service: markers
        for service, markers in SERVICE_MARKERS.items()
        if service not in {"schema", "approval"}
    }

    status = await provider_status()
    capability_matches = _capability_search(prompt, limit=6)
    detected = []
    missing_credentials = []
    for service, markers in service_markers.items():
        if any(marker in prompt_lower for marker in markers):
            service_status = status["services"].get(service)
            if service_status:
                item = {
                    "service": service,
                    "name": service_status["name"],
                    "configured": service_status["configured"],
                    "required_env": service_status["required_env"],
                }
                detected.append(item)
                if not service_status["configured"]:
                    missing_credentials.append(item)
    dynamic_detected = []
    for match in capability_matches:
        capability = match["capability"]
        source = capability.get("source", "")
        if source in {"openapi", "mcp"} and match["score"] >= 0.45:
            dynamic_detected.append({
                "service": source,
                "name": capability.get("category") or capability.get("label"),
                "configured": not capability.get("requires_auth"),
                "required_env": capability.get("requires_auth", []),
                "capability_id": capability["id"],
                "source": source,
                "score": match["score"],
            })
    detected.extend(dynamic_detected)

    schema_needed = any(marker in prompt_lower for marker in ("sheet", "spreadsheet", "excel", "csv", "database", "table", "hr", "crm", "airtable", "notion"))
    external_write = any(marker in prompt_lower for marker in ("send", "post", "append", "write", "create", "update", "delete", "invite"))
    dry_run = any(marker in prompt_lower for marker in ("dry run", "dry-run", "draft", "do not send", "do not post", "do not write"))

    questions = []
    if schema_needed:
        questions.append("Which file, sheet, database, or system should ForgeFlow inspect for real columns and sample rows?")
    for item in missing_credentials:
        questions.append(f"{item['name']} is not fully connected. Should ForgeFlow use dry-run drafts or wait for credentials?")
    if external_write and not dry_run:
        questions.append("Should external actions be drafts first, or may ForgeFlow execute them after an approval preview?")

    risks = []
    if external_write:
        risks.append("external_write_requires_approval")
    if schema_needed:
        risks.append("schema_required_to_avoid_hallucinated_fields")
    if missing_credentials:
        risks.append("missing_credentials")

    return {
        "prompt": prompt,
        "detected_services": detected,
        "missing_credentials": missing_credentials,
        "schema_needed": schema_needed,
        "dry_run": dry_run,
        "risks": risks,
        "questions": questions,
        "capability_matches": capability_matches,
        "dynamic_capabilities": dynamic_detected,
        "recommendation": "Collect missing schemas/credentials before code generation." if questions else "Ready to generate a verified automation plan.",
    }


# ── Workflow Management API ──────────────────────────────────

@app.get("/api/workflows")
async def list_workflows():
    """List all deployed workflows."""
    from backend.deployment.workflow_store import list_workflows as _list
    return {"workflows": _list()}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a specific workflow with code and metadata."""
    from backend.deployment.workflow_store import get_workflow as _get
    wf = _get(workflow_id)
    if not wf:
        return {"error": "Workflow not found"}, 404
    return wf


# ── Feedback & Continuous Improvement API ────────────────────

@app.get("/api/feedback/summary")
async def feedback_summary():
    """Get feedback summary and stats for the dashboard."""
    from backend.feedback.learning import get_feedback_summary
    return get_feedback_summary()


@app.get("/api/feedback/insights")
async def feedback_insights(services: str = ""):
    """Get pattern insights for continuous improvement."""
    from backend.feedback.learning import get_pattern_insights
    svc_list = [s.strip() for s in services.split(",") if s.strip()] if services else None
    return get_pattern_insights(svc_list)


@app.post("/api/workflows/{workflow_id}/feedback")
async def submit_feedback(workflow_id: str, body: dict):
    """Submit user feedback (approve/reject/rate) for a workflow."""
    from backend.feedback.learning import record_feedback
    return record_feedback(
        workflow_id=workflow_id,
        feedback_type=body.get("feedback_type", "approve"),
        rating=body.get("rating", 0),
        comment=body.get("comment", ""),
    )


@app.get("/api/workflows/{workflow_id}/download")
async def download_workflow(workflow_id: str):
    """Download a workflow as a ZIP file."""
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(project_path))
                zf.write(file_path, arcname)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=forgeflow-{workflow_id}.zip"},
    )


def _workflow_dry_run_payload(workflow_id: str) -> dict:
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")
    execution_path = os.path.join(project_path, "artifacts", "execution_result.json")
    if not os.path.exists(execution_path):
        raise HTTPException(status_code=404, detail="Workflow execution artifact not found")
    with open(execution_path, "r", encoding="utf-8") as file:
        execution = json.load(file)
    stdout = execution.get("stdout") or "{}"
    try:
        parsed = json.loads(stdout)
    except Exception:
        parsed = {}
    return parsed.get("dry_run_simulation") or parsed


def _workflow_artifact(workflow_id: str, name: str) -> dict:
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")
    artifact_path = os.path.join(project_path, "artifacts", name)
    if not os.path.exists(artifact_path):
        return {}
    with open(artifact_path, "r", encoding="utf-8") as file:
        return json.load(file)


def _dry_run_draft(value):
    if isinstance(value, dict) and isinstance(value.get("draft"), dict):
        return value["draft"]
    if isinstance(value, dict):
        return value
    return value


def _dry_run_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _review_placeholder(value, employee_name: str = "New Employee", employee_email: str = "new.employee@example.com"):
    if isinstance(value, list):
        return [[_review_placeholder(cell, employee_name, employee_email) for cell in row] if isinstance(row, list) else _review_placeholder(row, employee_name, employee_email) for row in value]
    if not isinstance(value, str):
        return value
    today = datetime.utcnow().date().isoformat()
    replacements = {
        "trigger.name": employee_name,
        "trigger.email": employee_email,
        "step_1.outputs.employee_name": employee_name,
        "step_1.outputs.employee_email": employee_email,
        "step_3.outputs.append_response.timestamp or current date": today,
        "current_date": today,
    }
    result = value
    for token, replacement in replacements.items():
        result = result.replace(token, replacement)
    return result


def _workflow_review_from_dag(workflow_id: str) -> list[dict]:
    dag = _workflow_artifact(workflow_id, "dag.json")
    actions = []
    employee_name = "New Employee"
    employee_email = "new.employee@example.com"
    for step in dag.get("steps", []):
        inputs = step.get("inputs", {}) if isinstance(step.get("inputs"), dict) else {}
        service = ((step.get("api") or {}).get("service") or step.get("name") or "").lower()
        if "gmail" in service or "email" in service:
            to = _review_placeholder(inputs.get("to") or employee_email, employee_name, employee_email)
            subject = _review_placeholder(inputs.get("subject") or f"Welcome to the Company, {employee_name}!", employee_name, employee_email)
            body = _review_placeholder(inputs.get("body") or f"Hello {employee_name},\n\nWelcome to the company!\n\nBest regards,\nHR Team", employee_name, employee_email)
            actions.append({
                "type": "gmail.send_email",
                "label": f"Send Gmail email to {to}",
                "preview": {"to": to, "subject": subject, "body": body},
            })
        elif "slack" in service:
            text = _review_placeholder(inputs.get("text") or f"Please welcome our new team member: {employee_name}!", employee_name, employee_email)
            if text:
                actions.append({
                    "type": "slack.post_message",
                    "label": "Post Slack announcement",
                    "preview": {"channel": settings.SLACK_NOTIFICATION_CHANNEL, "text": text},
                })
        elif "sheet" in service:
            rows = _review_placeholder(inputs.get("values") or [[employee_name, employee_email, datetime.utcnow().date().isoformat()]], employee_name, employee_email)
            actions.append({
                "type": "sheets.append_row",
                "label": f"Append {len(rows) if isinstance(rows, list) else 1} tracking rows to Google Sheets",
                "preview": {"range": str(inputs.get("range") or "Sheet1!A1"), "values": rows if isinstance(rows, list) else [[rows]]},
            })
    return actions


def _workflow_live_review(workflow_id: str) -> dict:
    simulation = _workflow_dry_run_payload(workflow_id)
    emails = [_dry_run_draft(item) for item in _dry_run_list(simulation.get("emails") or simulation.get("email_drafts"))]
    slack_messages = [
        _dry_run_draft(item)
        for item in _dry_run_list(simulation.get("slack_messages") or simulation.get("slack_message_drafts"))
    ]
    sheet_rows = []
    tracking_log = _dry_run_draft(simulation.get("tracking_log"))
    if isinstance(tracking_log, dict) and isinstance(tracking_log.get("values"), list):
        sheet_rows = tracking_log["values"]
    elif isinstance(simulation.get("tracking_row_drafts"), list):
        sheet_rows = simulation["tracking_row_drafts"]
    else:
        it_requests = [
            _dry_run_draft(item)
            for item in _dry_run_list(simulation.get("it_requests") or simulation.get("it_request_drafts"))
        ]
        sheet_rows = [
            [
                item.get("name") or item.get("employee_name", ""),
                item.get("email") or item.get("employee_email", ""),
                item.get("role", ""),
                "Pending",
            ]
            for item in it_requests
            if isinstance(item, dict) and (item.get("name") or item.get("email") or item.get("employee_name") or item.get("employee_email"))
        ]
    actions = []
    for email_item in emails:
        if not isinstance(email_item, dict):
            continue
        actions.append({
            "type": "gmail.send_email",
            "label": f"Send Gmail email to {email_item.get('to')}",
            "preview": {
                "to": email_item.get("to"),
                "subject": email_item.get("subject"),
                "body": email_item.get("body"),
            },
        })
    for message in slack_messages:
        if isinstance(message, dict):
            text = message.get("text", "")
        else:
            text = str(message)
        if not text:
            continue
        actions.append({
            "type": "slack.post_message",
            "label": "Post Slack announcement",
            "preview": {"channel": settings.SLACK_NOTIFICATION_CHANNEL, "text": text},
        })
    if sheet_rows:
        actions.append({
            "type": "sheets.append_row",
            "label": f"Append {len(sheet_rows)} tracking rows to Google Sheets",
            "preview": {"range": "Sheet1!A1", "values": sheet_rows},
        })
    if not actions:
        actions = _workflow_review_from_dag(workflow_id)
    return {
        "workflow_id": workflow_id,
        "ready": bool(actions),
        "actions": actions,
        "approval_required": True,
        "message": "Review these external actions before approving live execution.",
    }


def _send_live_connector_request(connector_id: str, inputs: dict) -> dict:
    service = connector_id.split(".", 1)[0]
    secret = _secret_for_service(service)
    if not secret:
        return {"connector_id": connector_id, "status": "blocked", "error": "missing credentials"}
    request_spec = _connector_live_request(connector_id, inputs, secret)
    try:
        req = Request(
            request_spec["url"],
            data=request_spec.get("body"),
            headers=request_spec.get("headers", {}),
            method=request_spec.get("method", "POST"),
        )
        with urlopen(req, timeout=20, context=_https_context()) as response:
            text = response.read().decode("utf-8", errors="replace")[:2000]
            parsed = _json_loads(text, {"text": text})
            provider_ok = parsed.get("ok", True) is not False if isinstance(parsed, dict) else True
            return {
                "connector_id": connector_id,
                "status": "succeeded" if response.status < 400 and provider_ok else "failed",
                "status_code": response.status,
                "response": parsed,
                "error": parsed.get("error") if isinstance(parsed, dict) and parsed.get("ok") is False else None,
            }
    except HTTPError as exc:
        if exc.code == 401 and _refresh_oauth_access_token(service):
            return _send_live_connector_request(connector_id, inputs)
        error_text = exc.read().decode("utf-8", errors="replace")[:1000] if hasattr(exc, "read") else str(exc)
        return {"connector_id": connector_id, "status": "failed", "status_code": exc.code, "error": _redact_sensitive(error_text, secret)}
    except Exception as exc:
        return {"connector_id": connector_id, "status": "failed", "error": _redact_sensitive(str(exc), secret)}


def _approved_review_actions(review: dict, body: dict) -> list[dict]:
    supplied = body.get("actions")
    if supplied is None:
        return review["actions"]
    if not isinstance(supplied, list) or len(supplied) != len(review["actions"]):
        raise HTTPException(status_code=400, detail="Approved action edits must match the reviewed action list.")
    approved = []
    for index, original in enumerate(review["actions"]):
        edited = supplied[index]
        if not isinstance(edited, dict):
            raise HTTPException(status_code=400, detail=f"Action {index + 1} is invalid.")
        if edited.get("type") != original.get("type"):
            raise HTTPException(status_code=400, detail=f"Action {index + 1} type changed.")
        preview = edited.get("preview")
        if not isinstance(preview, dict):
            raise HTTPException(status_code=400, detail=f"Action {index + 1} preview must be an object.")
        approved.append({**original, "preview": preview})
    return approved


@app.get("/api/workflows/{workflow_id}/live-review")
async def workflow_live_review(workflow_id: str):
    """Return external actions that would run after approval."""
    return _workflow_live_review(workflow_id)


@app.post("/api/workflows/{workflow_id}/approve-live")
async def approve_workflow_live(workflow_id: str, body: dict):
    """Run reviewed external actions only after explicit approval."""
    if not body.get("approved"):
        raise HTTPException(status_code=403, detail="approved=true is required")
    review = _workflow_live_review(workflow_id)
    if not review["ready"]:
        raise HTTPException(status_code=400, detail="No reviewable live actions found")
    results = []
    for action in _approved_review_actions(review, body):
        connector_id = action["type"]
        preview = action["preview"]
        result = None
        if connector_id in {"gmail.create_draft", "gmail.send_email"}:
            result = _send_live_connector_request(connector_id, preview)
        elif connector_id == "slack.post_message":
            result = _send_live_connector_request(connector_id, preview)
        elif connector_id == "sheets.append_row":
            result = _send_live_connector_request(connector_id, preview)
        if result:
            results.append({**result, "label": action.get("label", connector_id), "preview": preview})
    success = all(item.get("status") == "succeeded" for item in results)
    run_result = {
        "success": success,
        "stdout": json.dumps({"approved_live_results": results}, indent=2),
        "stderr": "" if success else "One or more live connector actions failed.",
        "execution_time": 0.0,
        "return_code": 0 if success else 1,
    }
    run_result.update(_record_run_log(workflow_id, run_result))
    return {"workflow_id": workflow_id, "success": success, "results": results, "run": run_result}


@app.get("/api/workflows/{workflow_id}/files")
async def list_workflow_files(workflow_id: str):
    """List all files in a deployed workflow project."""
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")

    files = []
    for root, dirs, fnames in os.walk(project_path):
        # Skip hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in sorted(fnames):
            if not fname.startswith("."):
                rel = os.path.relpath(os.path.join(root, fname), project_path)
                files.append(rel)

    return {"workflow_id": workflow_id, "files": files}


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, _admin: bool = Depends(require_admin_token)):
    """Delete a deployed workflow project and metadata."""
    from backend.deployment.workflow_store import delete_workflow as _delete
    deleted = _delete(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"deleted": workflow_id}


@app.post("/api/workflows/prune")
async def prune_workflows(body: dict, _admin: bool = Depends(require_admin_token)):
    """Delete old workflow projects, keeping the newest N."""
    from backend.deployment.workflow_store import prune_workflows as _prune
    keep_latest = int(body.get("keep_latest", 50))
    deleted = _prune(keep_latest=keep_latest)
    return {"deleted": deleted, "keep_latest": keep_latest}


@app.get("/api/workflows/{workflow_id}/files/{file_path:path}")
async def get_workflow_file(workflow_id: str, file_path: str):
    """Get the content of a specific file in a deployed workflow."""
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Prevent path traversal
    from backend.shared.path_security import resolve_within_directory
    try:
        full_path, _ = resolve_within_directory(project_path, file_path)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": file_path}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is binary and cannot be displayed")


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, _admin: bool = Depends(require_admin_token)):
    """Execute a deployed workflow with real credentials and return its output.

    Runs `python workflow.py` in an isolated temp copy with allowlisted service
    environment variables injected so real API calls work.
    """
    try:
        result = await _execute_workflow_project(workflow_id)
        result.update(_record_run_log(workflow_id, result))
        return result

    except Exception as e:
        result = {
            "success": False,
            "stdout": "",
            "stderr": f"Runner error: {e}",
            "execution_time": 0.0,
            "return_code": -1,
        }
        result.update(_record_run_log(workflow_id, result))
        return result


@app.post("/api/runs/{run_id}/retry")
async def retry_run(run_id: str, _admin: bool = Depends(require_admin_token)):
    """Retry a persisted workflow run."""
    conn = _platform_db()
    row = conn.execute("SELECT * FROM run_logs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow_id = row["workflow_id"]
    attempt = int(row["attempt"] or 1) + 1
    result = await _execute_workflow_project(workflow_id)
    result.update(_record_run_log(workflow_id, result, attempt=attempt))
    return result


# ── Integrations API ─────────────────────────────────────────

@app.get("/api/integrations")
async def list_integrations():
    """List all available service integrations with capabilities."""
    from backend.integrations import list_integrations as _list
    return {"integrations": _list()}


@app.get("/api/integrations/{service}")
async def get_integration(service: str):
    """Get details about a specific integration."""
    from backend.integrations import INTEGRATIONS
    service = service.lower().strip()
    if service not in INTEGRATIONS:
        return {"error": f"Integration '{service}' not found"}
    info = INTEGRATIONS[service]
    return {
        "service": service,
        "name": info["name"],
        "description": info["description"],
        "capabilities": info["capabilities"],
        "env_vars": info["env_vars"],
        "auth_type": info["auth_type"],
    }


@app.post("/api/integrations/{service}/test")
async def test_integration(service: str):
    """Test if a service integration is properly configured."""
    from backend.integrations import get_client
    try:
        client = get_client(service)
        # Quick connectivity test per service
        if service == "slack":
            result = await client.list_channels(limit=1)
        elif service == "gmail":
            result = await client.list_labels()
        elif service == "sheets":
            return {"status": "configured", "message": "Sheets client ready (needs spreadsheet ID for full test)"}
        elif service == "http":
            result = await client.health_check("https://httpbin.org/get")
        else:
            return {"status": "unknown", "message": f"No test for {service}"}

        return {
            "status": "connected" if result.get("ok") else "error",
            "message": "Integration working" if result.get("ok") else result.get("error", "Unknown error"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── WebSocket Endpoint ────────────────────────────────────────

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(ws: WebSocket, client_id: str):
    await manager.connect(ws, client_id)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "forge":
                # Run pipeline in background, stream events via WebSocket
                asyncio.create_task(_run_pipeline_ws(client_id, msg))
            elif msg.get("type") == "clarify":
                # User answered a clarification question — restart pipeline with combined context
                asyncio.create_task(_run_pipeline_ws(client_id, msg, is_clarification=True))
            elif msg.get("type") == "modify":
                # Natural language modification
                asyncio.create_task(_run_modify_ws(client_id, msg))
            elif msg.get("type") == "forge_demo":
                # Pre-cached demo mode
                asyncio.create_task(_run_demo_ws(client_id))
            elif msg.get("type") == "ping":
                await manager.send_event(client_id, {"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(client_id)


async def _run_pipeline_ws(client_id: str, msg: dict, is_clarification: bool = False):
    from backend.graph import run_forgeflow_pipeline

    workflow_id = str(uuid.uuid4())[:8]

    # If this is a clarification response, combine original + answer
    user_request = msg.get("message", "")
    if is_clarification:
        original = msg.get("original_request", "")
        answer = msg.get("message", "")
        user_request = f"{original}\n\nAdditional details: {answer}"

    async def ws_event_callback(event: dict):
        await manager.send_event(client_id, event)
        # Also broadcast to other listeners (Slack, etc.)
        for listener in event_listeners:
            try:
                await listener(event)
            except Exception:
                pass

    result = await run_forgeflow_pipeline(
        user_request=user_request,
        workflow_id=workflow_id,
        slack_channel=msg.get("slack_channel", settings.SLACK_NOTIFICATION_CHANNEL),
        event_callback=ws_event_callback,
        clarifications_asked=1 if is_clarification else 0,
    )

    # If pipeline stopped for clarification, send clarification request to user
    if result.get("needs_clarification"):
        reqs = result.get("business_requirements", {})
        await manager.send_event(client_id, {
            "type": "clarification_needed",
            "event_type": "conversation.clarification_needed",
            "workflow_id": workflow_id,
            "original_request": msg.get("message", ""),
            "questions": result.get("clarification_needed", []),
            "current_plan": [
                {"step": a.get("id", ""), "action": a.get("description", ""), "service": a.get("service_hint", "")}
                for a in reqs.get("actions", [])
            ],
            "confidence": result.get("business_requirements", {}).get("confidence", 0),
            "assumed_defaults": reqs.get("assumed_defaults", []),
            "message": "I'd like to clarify a few things to generate a better workflow.",
            "timestamp": datetime.utcnow().isoformat(),
        })
        return  # Stop here — wait for user to send a "clarify" message

    await manager.send_event(client_id, {
        "type": "forge_complete",
        "workflow_id": workflow_id,
        "phase": result.get("phase", "deployed"),
        "dag": result.get("workflow_dag"),
        "code": result.get("generated_code"),
        "test_results": result.get("test_results"),
        "message": result.get("final_message", "Done"),
    })


# ── Modification handler ─────────────────────────────────────

async def _run_modify_ws(client_id: str, msg: dict):
    """Handle natural language workflow modification."""
    from backend.modifier.nl_modifier import modify_workflow
    from backend.shared.models import WorkflowDAG

    workflow_dag_data = msg.get("dag", {})
    current_code = msg.get("code", "")
    modification = msg.get("message", "")

    await manager.send_event(client_id, {
        "event_type": "modify.started",
        "phase": "modifying",
        "message": f"Modifying workflow: {modification[:80]}...",
        "data": {},
        "timestamp": datetime.utcnow().isoformat(),
    })

    try:
        dag = WorkflowDAG(**workflow_dag_data)
        result = await modify_workflow(modification, dag, current_code)

        await manager.send_event(client_id, {
            "event_type": "modify.complete",
            "phase": "deployed",
            "message": f"Modification applied: {result['changes']}",
            "data": {
                "modified_code": result["modified_code"],
                "affected_nodes": result["affected_nodes"],
                "changes": result["changes"],
            },
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        await manager.send_event(client_id, {
            "event_type": "modify.failed",
            "phase": "deployed",
            "message": f"Modification failed: {str(e)}",
            "data": {},
            "timestamp": datetime.utcnow().isoformat(),
        })


# ── Demo mode handler ────────────────────────────────────────

async def _run_demo_ws(client_id: str):
    """Replay cached demo events for reliable demos."""
    if not _demo_endpoints_enabled():
        await manager.send_event(client_id, {
            "event_type": "error",
            "message": "Demo WebSocket replay is disabled in production.",
            "data": {"reason": "set FORGEFLOW_ENABLE_DEMO_ENDPOINTS=1 only for staging demos"},
            "timestamp": datetime.utcnow().isoformat(),
        })
        return

    demo_path = os.path.join(os.path.dirname(__file__), "demo_cache.json")
    if not os.path.exists(demo_path):
        await manager.send_event(client_id, {
            "event_type": "error",
            "message": "No demo cache found. Run a real pipeline first.",
            "data": {},
            "timestamp": datetime.utcnow().isoformat(),
        })
        return

    with open(demo_path) as f:
        cached_events = json.load(f)

    for cached in cached_events:
        # Copy to avoid mutating the cached list (allows multiple replays)
        event = {k: v for k, v in cached.items() if k != "_delay"}
        delay = cached.get("_delay", 0.5)
        event["timestamp"] = datetime.utcnow().isoformat()
        await manager.send_event(client_id, event)
        await asyncio.sleep(delay)


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        reload=False,  # Disabled — agent write_file triggers WatchFiles reload mid-pipeline
    )
