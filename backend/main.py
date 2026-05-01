import asyncio
import base64
import csv
import hmac
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
import io
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlencode

logging.getLogger("slack").setLevel(logging.WARNING)
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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
PLATFORM_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "forgeflow_platform.db")

CAPABILITY_REGISTRY = [
    {
        "id": "schema.inspect_file",
        "label": "Inspect Uploaded File",
        "category": "Discovery",
        "risk": "read_only",
        "requires_auth": [],
        "description": "Read CSV or XLSX headers and sample rows before planning.",
        "dry_run": True,
    },
    {
        "id": "slack.post_message",
        "label": "Post Slack Message",
        "category": "Messaging",
        "risk": "external_write",
        "requires_auth": ["SLACK_BOT_TOKEN"],
        "description": "Send or draft Slack channel messages with approval gates.",
        "dry_run": True,
    },
    {
        "id": "gmail.send_email",
        "label": "Send Gmail Email",
        "category": "Messaging",
        "risk": "external_write",
        "requires_auth": ["GMAIL_ACCESS_TOKEN", "GMAIL_SENDER_EMAIL"],
        "description": "Draft or send email messages through Gmail.",
        "dry_run": True,
    },
    {
        "id": "sheets.append_row",
        "label": "Append Google Sheets Row",
        "category": "Data",
        "risk": "external_write",
        "requires_auth": ["GOOGLE_SHEETS_ACCESS_TOKEN"],
        "description": "Append validated rows to an existing spreadsheet.",
        "dry_run": True,
    },
    {
        "id": "http.request",
        "label": "Call HTTP API",
        "category": "API",
        "risk": "network_call",
        "requires_auth": [],
        "description": "Call generic REST APIs from a validated request schema.",
        "dry_run": True,
    },
    {
        "id": "approval.wait",
        "label": "Human Approval Gate",
        "category": "Safety",
        "risk": "approval_required",
        "requires_auth": [],
        "description": "Pause before sending, posting, writing, deleting, or changing access.",
        "dry_run": True,
    },
]

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
        "id": "webhook_runtime",
        "name": "Hosted Webhook Runtime",
        "status": "planned",
        "description": "Expose a webhook URL that triggers a selected automation version.",
        "requires": ["public runtime", "auth policy"],
    },
]


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

        CREATE TABLE IF NOT EXISTS eval_runs (
            id TEXT PRIMARY KEY,
            suite TEXT NOT NULL,
            score REAL NOT NULL,
            cases_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
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
    return {
        "gmail": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "redirect_uri_env": "GOOGLE_OAUTH_REDIRECT_URI",
            "scopes": ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"],
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
    for service, info in SUPPORTED_SERVICES.items():
        status_by_service[service] = _upsert_connector_state(
            service=service,
            status="connected" if _env_status(info.get("env_vars", ()))["configured"] else "missing_credentials",
            auth_type=info.get("auth_type", "api_key"),
            scopes=_oauth_specs().get(service, {}).get("scopes", []),
            env_vars=info.get("env_vars", ()),
            metadata={"name": info["name"], "source": "environment"},
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
    hidden_terms = ("deriv", "gene" + "sis")
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
    return {"run_id": run_id, "status": status}


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
    queue_id = _stable_id("queue", {"workflow_id": workflow_id, "priority": priority})
    now = _now_iso()
    conn = _platform_db()
    conn.execute(
        """
        INSERT INTO run_queue
        (id, workflow_id, status, payload_json, priority, attempts, max_attempts, created_at, updated_at)
        VALUES (?, ?, 'queued', ?, ?, 0, ?, ?, ?)
        """,
        (queue_id, workflow_id, json.dumps(payload or {}), priority, max_attempts, now, now),
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
    try:
        result = await _execute_workflow_project(row["workflow_id"])
    except HTTPException as exc:
        result = {"success": False, "stdout": "", "stderr": exc.detail, "execution_time": 0.0, "return_code": -1}
    except Exception as exc:
        result = {"success": False, "stdout": "", "stderr": str(exc), "execution_time": 0.0, "return_code": -1}
    run_meta = _record_run_log(row["workflow_id"], result, attempt=attempts)
    final_status = "succeeded" if result.get("success") else ("failed" if attempts >= int(row["max_attempts"] or 3) else "queued")
    conn = _platform_db()
    conn.execute(
        """
        UPDATE run_queue
        SET status = ?, last_error = ?, run_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (final_status, None if result.get("success") else result.get("stderr", "failed"), run_meta["run_id"], _now_iso(), queue_id),
    )
    conn.commit()
    conn.close()
    return {"queue_id": queue_id, "queue_status": final_status, "run": {**result, **run_meta}}


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


def _extract_openapi_capabilities(spec: dict) -> list[dict]:
    title = spec.get("info", {}).get("title", "OpenAPI")
    capabilities_data = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation = operation if isinstance(operation, dict) else {}
            operation_id = operation.get("operationId") or f"{method}_{path}".strip("/").replace("/", "_").replace("{", "").replace("}", "")
            capabilities_data.append({
                "id": f"openapi.{operation_id}",
                "label": operation.get("summary") or operation_id.replace("_", " ").title(),
                "category": title,
                "risk": "network_call" if method.lower() == "get" else "external_write",
                "requires_auth": [],
                "description": f"{method.upper()} {path}",
                "dry_run": True,
                "source": "openapi",
                "method": method.upper(),
                "path": path,
            })
    return capabilities_data


def _extract_mcp_capabilities(manifest: dict) -> list[dict]:
    tools = manifest.get("tools") or manifest.get("capabilities") or []
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


def _product_gap_analysis() -> dict:
    connectors = _list_connector_states()
    pending_approvals = [item for item in _list_approvals() if item["status"] == "pending"]
    triggers = _list_triggers()
    runs = _collect_run_history(limit=20)
    ingested_count = len(_all_capabilities()) - len(CAPABILITY_REGISTRY)
    active_triggers = [item for item in triggers if item["status"] == "active"]
    failed_runs = [item for item in runs if not item["success"]]

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
            "status": "pass" if any(item["env_status"]["configured"] for item in connectors) else "warn",
            "detail": "At least one real connector is configured" if any(item["env_status"]["configured"] for item in connectors) else "No real connector credentials configured yet",
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
            "status": "pass" if _list_credentials() else "warn",
            "detail": f"{len(_list_credentials())} encrypted credentials stored",
        },
        {
            "id": "prompt_evals",
            "label": "Prompt evals",
            "status": "pass" if _list_eval_runs() else "warn",
            "detail": f"{len(_list_eval_runs())} eval runs recorded",
        },
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "score": round((len(checks) - len(blockers)) / len(checks) * 100),
        "checks": checks,
        "blockers": blockers,
        "next": [
            "Complete OAuth token exchange and encrypted refresh-token storage.",
            "Activate at least one real scheduled or webhook workflow.",
            "Run prompt evals against real business fixtures before claiming broad automation coverage.",
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

    yield


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
        services[key] = {
            "name": info["name"],
            "configured": all(bool(os.getenv(env_name, "")) for env_name in required_env),
            "required_env": required_env,
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


@app.get("/api/capabilities")
async def capabilities():
    """List typed capabilities the planner should compose before custom code."""
    return {"capabilities": _all_capabilities()}


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


@app.post("/api/runs/queue/{queue_id}/process")
async def process_run_queue_item(queue_id: str):
    return await _process_queue_item(queue_id)


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
    event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, "running")
    try:
        result = await _execute_workflow_project(trigger["workflow_id"])
        run_meta = _record_run_log(trigger["workflow_id"], result)
        status = "success" if result.get("success") else "failed"
        event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, status, run_meta["run_id"])
        return {"accepted": True, "event": event, "run": {**result, **run_meta}}
    except HTTPException as exc:
        result = {
            "success": False,
            "stdout": "",
            "stderr": exc.detail,
            "execution_time": 0.0,
            "return_code": -1,
        }
        run_meta = _record_run_log(trigger["workflow_id"], result)
        event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, "failed", run_meta["run_id"])
        return {"accepted": True, "event": event, "run": {**result, **run_meta}}
    except Exception as exc:
        result = {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "execution_time": 0.0,
            "return_code": -1,
        }
        run_meta = _record_run_log(trigger["workflow_id"], result)
        event = _record_trigger_event(trigger_id, trigger["workflow_id"], "webhook", body, "failed", run_meta["run_id"])
        return {"accepted": True, "event": event, "run": {**result, **run_meta}}


@app.get("/api/triggers/events")
async def trigger_events():
    return {"events": _list_trigger_events()}


@app.get("/api/deploy/targets")
async def deployment_targets():
    targets = []
    for target in DEPLOYMENT_TARGETS:
        targets.append({
            **target,
            "env_status": _env_status(target.get("requires_env", [])),
        })
    return {"targets": targets}


@app.get("/api/deploy/plans")
async def deployment_plans():
    return {"plans": _list_deployment_plans(), "activations": _list_deployment_activations()}


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


@app.get("/api/connectors/oauth/{service}/start")
async def start_oauth_connector(service: str):
    """Return an OAuth start scaffold without storing credentials."""
    service = service.lower()
    spec = _oauth_specs().get(service)
    if not spec:
        raise HTTPException(status_code=404, detail="OAuth connector not available for this service")
    state = _stable_id("oauth", {"service": service})
    client_id = os.getenv(spec["client_id_env"], "")
    redirect_uri = os.getenv(spec["redirect_uri_env"], "http://127.0.0.1:8000/api/connectors/oauth/callback")
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
        "missing_env": [
            name for name in (spec["client_id_env"], spec["client_secret_env"], spec["redirect_uri_env"])
            if not os.getenv(name, "")
        ],
        "message": "OAuth session created. Complete callback after provider authorization.",
    }


@app.get("/api/connectors")
async def connector_lifecycle():
    return {
        "connectors": _list_connector_states(),
        "oauth_sessions": _list_oauth_sessions(),
        "credentials": _list_credentials(),
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
    connector = _upsert_connector_state(
        service=service,
        status="authorization_code_received",
        auth_type="oauth2",
        scopes=_json_loads(session["scopes_json"], []),
        env_vars=spec.get("env_vars", []) if spec else [],
        metadata={
            "state": state,
            "code_received": True,
            "token_exchange": "pending_server_side_secret_exchange",
            "token_url": spec.get("token_url") if spec else None,
        },
    )
    return {"service": service, "status": connector["status"], "connector": connector}


@app.get("/api/evals/suites")
async def eval_suites():
    return {"suites": [{"id": key, "cases": value} for key, value in EVAL_SUITES.items()], "runs": _list_eval_runs()}


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
        "slack": ("slack", "channel", "#"),
        "gmail": ("gmail", "email", "mail", "inbox"),
        "sheets": ("sheet", "spreadsheet", "google sheets", "row", "excel"),
        "http": ("http", "api", "webhook", "url", "endpoint"),
    }

    status = await provider_status()
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

    schema_needed = any(marker in prompt_lower for marker in ("sheet", "spreadsheet", "excel", "csv", "database", "table", "hr", "crm"))
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
