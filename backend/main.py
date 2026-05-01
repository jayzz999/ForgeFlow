import asyncio
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
import io
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime

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


def _workflow_run_env() -> dict[str, str]:
    """Allowlist env vars passed to generated workflow execution."""
    env = {"PYTHONUNBUFFERED": "1"}
    for key, value in os.environ.items():
        if key in RUN_ENV_EXACT or any(key.startswith(prefix) for prefix in RUN_ENV_PREFIXES):
            env[key] = value
    return env


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
    for workflow in _visible_workflows(_list(limit=max(limit * 2, limit))):
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
            "workflow_id": workflow_id,
            "name": workflow.get("name", workflow_id),
            "created_at": saved_at,
            "success": bool(execution.get("success")),
            "execution_time": execution.get("execution_time"),
            "tests_passed": tests.get("passed", 0),
            "tests_total": tests.get("total", 0),
            "services": [s for s in (workflow.get("services") or "").split(",") if s],
        })

    return runs[:limit]


def _visible_workflows(workflows: list[dict]) -> list[dict]:
    """Hide legacy rows from removed product areas without deleting history."""
    hidden_terms = ("deriv", "genesis")
    visible = []
    for workflow in workflows:
        text = " ".join(str(workflow.get(key, "")) for key in ("name", "description", "services", "user_request")).lower()
        if any(term in text for term in hidden_terms):
            continue
        visible.append(workflow)
    return visible

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

    return {
        "metrics": {
            "total_workflows": len(workflows),
            "configured_services": configured_services,
            "available_services": len(service_values),
            "recent_successful_runs": sum(1 for run in recent_runs if run["success"]),
            "approval_queue": 0,
        },
        "workflows": workflows,
        "recent_runs": recent_runs,
        "llm": status["llm"],
        "embeddings": status["embeddings"],
    }


@app.get("/api/capabilities")
async def capabilities():
    """List typed capabilities the planner should compose before custom code."""
    return {"capabilities": CAPABILITY_REGISTRY}


@app.get("/api/templates")
async def templates():
    """List reusable automation templates."""
    return {"templates": TEMPLATE_GALLERY}


@app.get("/api/runs")
async def run_history():
    """Return recent local workflow execution artifacts."""
    return {"runs": _collect_run_history(limit=30)}


@app.get("/api/approvals")
async def approvals():
    """Return current approval queue and product approval policy."""
    return {
        "pending": [],
        "policy": [
            "Preview and approve before sending emails or Slack messages.",
            "Preview and approve before writing to external systems.",
            "Require explicit confirmation before deletions or permission changes.",
            "Dry-run mode never reads credentials or calls external APIs.",
        ],
    }


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
    import asyncio as _asyncio
    from backend.deployment.workflow_store import get_workflow_project_path

    project_path = get_workflow_project_path(workflow_id)
    if not project_path:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_file = os.path.join(project_path, "workflow.py")
    if not os.path.exists(workflow_file):
        raise HTTPException(status_code=404, detail="workflow.py not found in project")

    start = datetime.utcnow()

    try:
        with tempfile.TemporaryDirectory(prefix=f"forgeflow_run_{workflow_id}_") as run_dir:
            shutil.copytree(project_path, run_dir, dirs_exist_ok=True)
            req_file = os.path.join(run_dir, "requirements.txt")

            # Step 1: Install dependencies in the isolated run directory.
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

            # Step 2: Run the workflow with only allowlisted service env vars.
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
        stdout_str = _trim_output(stdout_b.decode("utf-8", errors="replace"))
        stderr_str = _trim_output(stderr_b.decode("utf-8", errors="replace"))

        return {
            "success": proc.returncode == 0,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "execution_time": round(elapsed, 2),
            "return_code": proc.returncode,
        }

    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Runner error: {e}",
            "execution_time": 0.0,
            "return_code": -1,
        }


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
