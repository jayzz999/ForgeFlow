from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── API Discovery Models ──────────────────────────────────────

class AuthType(str, Enum):
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH2 = "oauth2"
    WEBSOCKET_TOKEN = "websocket_token"
    NONE = "none"


class APIEndpoint(BaseModel):
    service: str  # e.g. "Slack", "Gmail", "Deriv"
    endpoint: str  # e.g. "/chat.postMessage"
    method: str  # GET, POST, WS
    description: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    auth_type: AuthType = AuthType.API_KEY
    base_url: str = ""
    code_example: str = ""
    confidence: float = 0.0


# ── Workflow DAG Models ───────────────────────────────────────

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep(BaseModel):
    id: str
    name: str
    description: str
    api: Optional[APIEndpoint] = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    error_handling: str = "retry_3x"
    condition: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    step_type: str = "api_call"  # api_call | trigger | condition | delay


class WorkflowDAG(BaseModel):
    id: str
    name: str
    description: str
    trigger: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(default_factory=list)
    environment_vars: list[str] = Field(default_factory=list)


# ── Execution Models ─────────────────────────────────────────

class DebugDiagnosis(BaseModel):
    category: str  # AUTH_ERROR, SCHEMA_MISMATCH, RATE_LIMIT, MISSING_PARAM, LOGIC_ERROR, NETWORK_ERROR
    root_cause: str
    fix_description: str
    fixed_function: str
    diff: str = ""


class ExecutionResult(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    return_value: Any = None
    execution_time: float = 0.0


# ── Event Models ──────────────────────────────────────────────

class PipelineEvent(BaseModel):
    event_type: str
    phase: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[str] = None


# ── API Request/Response Models ───────────────────────────────

class ForgeRequest(BaseModel):
    message: str
    workflow_id: Optional[str] = None
    slack_channel: Optional[str] = None


class ForgeResponse(BaseModel):
    workflow_id: str
    phase: str
    message: str
    dag: Optional[dict] = None
    code: Optional[str] = None
    events: list[dict] = Field(default_factory=list)
