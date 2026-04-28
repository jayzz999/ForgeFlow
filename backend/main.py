import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
import io
from contextlib import asynccontextmanager
from datetime import datetime

logging.getLogger("slack").setLevel(logging.WARNING)
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    slack_disabled = os.getenv("SLACK_DISABLED", "0") in ("1", "true", "yes")
    if _slack_app_real and not slack_disabled:
        asyncio.create_task(_safe_start_slack_bot())
        print("[Slack] Bot starting in Socket Mode (bidirectional)")
    elif slack_disabled:
        print("[Slack] Disabled by SLACK_DISABLED=1")
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
    if provider not in {"groq", "gemini"}:
        provider = "groq"

    llm_providers = {
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
                    "pip", "install", "-q", "-r", req_file,
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
                "python", "workflow.py",
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
