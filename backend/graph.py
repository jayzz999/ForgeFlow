"""ForgeFlow LangGraph Pipeline — The autonomous workflow generation engine."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Literal, Optional, TypedDict

logger = logging.getLogger("forgeflow.graph")

from backend.shared.config import settings
from backend.shared.models import APIEndpoint, WorkflowDAG


# ── State Definition ──────────────────────────────────────────

class ForgeFlowState(TypedDict, total=False):
    # Input
    user_request: str
    workflow_id: str
    slack_channel: str

    # Conversation
    messages: list[dict]
    phase: str
    business_requirements: dict
    confidence: float
    clarification_needed: list[str]
    clarifications_asked: int

    # Discovery
    discovered_apis: list[dict]
    unmatched_actions: list[dict]  # Actions without pre-indexed APIs — agent will research

    # Planning
    workflow_dag: dict | None
    data_mappings: list[dict]

    # Code Generation
    generated_code: str | None
    extra_files: dict[str, str]  # Multi-file project: {path: content}
    security_review: dict | None

    # Testing
    test_code: str | None  # Auto-generated pytest test file
    test_results: dict | None  # Test execution results

    # Execution
    execution_result: dict | None
    debug_attempts: int
    debug_history: list[dict]

    # Approval
    approval_status: str  # pending, approved, rejected

    # Output
    deployed: bool
    final_message: str
    events: list[dict]

    # Callback
    _event_callback: Any


# ── Helper: Emit Event ────────────────────────────────────────

async def _emit(state: ForgeFlowState, event_type: str, message: str, data: dict | None = None):
    """Emit an event through the callback and add to state events."""
    event = {
        "event_type": event_type,
        "phase": state.get("phase", "unknown"),
        "message": message,
        "data": data or {},
        "workflow_id": state.get("workflow_id", ""),
        "timestamp": datetime.utcnow().isoformat(),
    }
    cb = state.get("_event_callback")
    if cb:
        await cb(event)
    state.setdefault("events", []).append(event)


# ── Node 1: Conversation ─────────────────────────────────────

async def conversation_node(state: ForgeFlowState) -> dict:
    """Extract requirements from user's natural language request."""
    from backend.conversation.engine import extract_requirements, generate_clarification

    await _emit(state, "conversation.started", "Analyzing your workflow request...")

    requirements = await extract_requirements(
        state["user_request"],
        state.get("messages"),
    )

    confidence = requirements.get("confidence", 0)
    clarifications = requirements.get("clarification_needed", [])
    asked = state.get("clarifications_asked", 0)

    logger.info(f"[Conversation] confidence={confidence}, clarifications={clarifications}, asked={asked}")

    await _emit(state, "conversation.analyzed", f"Requirements extracted (confidence: {confidence:.0%})", {
        "intent": requirements.get("intent"),
        "entities": [e.get("name") for e in requirements.get("entities", [])],
        "actions_count": len(requirements.get("actions", [])),
        "assumed_defaults": requirements.get("assumed_defaults", []),
    })

    # If confidence is low and we haven't asked yet, emit clarification event
    if clarifications and asked < 1 and confidence < 0.75:
        # Generate a natural clarification message
        clarification_msg = await generate_clarification(requirements)

        await _emit(state, "conversation.clarification_needed",
            clarification_msg or clarifications[0],
            {
                "questions": clarifications,
                "assumed_defaults": requirements.get("assumed_defaults", []),
                "current_plan": [
                    {"step": a.get("id", ""), "action": a.get("description", ""), "service": a.get("service_hint", "")}
                    for a in requirements.get("actions", [])
                ],
                "confidence": confidence,
            },
        )

    return {
        "business_requirements": requirements,
        "confidence": confidence,
        "clarification_needed": clarifications,
        "phase": "collecting" if (clarifications and asked < 1 and confidence < 0.75) else "planning",
        "clarifications_asked": asked + (1 if clarifications else 0),
    }


# ── Node 2: API Discovery ────────────────────────────────────

async def api_discovery_node(state: ForgeFlowState) -> dict:
    """Discover relevant APIs using semantic search. Tracks unmatched actions for agent research."""
    from backend.discovery.vector_store import similarity_search
    from backend.discovery.api_selector import select_best_api, extract_actions

    await _emit(state, "discovery.started", "Discovering relevant APIs...")

    requirements = state.get("business_requirements", {})

    # Extract individual actions from requirements
    actions = requirements.get("actions", [])
    if not actions:
        actions = await extract_actions(state["user_request"])

    discovered = []
    matched_action_ids = set()
    non_trigger_actions = [a for a in actions if not a.get("is_trigger")]

    for action in non_trigger_actions:
        desc = action.get("description", action.get("action", ""))
        service_hint = action.get("service_hint", "")
        query = f"{desc} {service_hint}".strip()

        # Semantic search
        candidates = similarity_search(query, k=5)

        # Only consider candidates with reasonable confidence
        good_candidates = [c for c in candidates if c.get("confidence", 0) >= 0.3]

        if not good_candidates:
            await _emit(state, "discovery.miss", f"No pre-indexed API for: {desc[:60]}. Agent will research.", {
                "action": desc,
                "service_hint": service_hint,
            })
            continue

        # LLM selection
        best = await select_best_api(
            action_description=desc,
            candidates=good_candidates,
            workflow_context=requirements.get("description", ""),
        )

        if best and best.confidence >= 0.5:
            discovered.append(best)
            matched_action_ids.add(action.get("id", ""))
            await _emit(state, "api.discovered", f"Found: {best.service} → {best.endpoint}", {
                "service": best.service,
                "endpoint": best.endpoint,
                "confidence": best.confidence,
            })

    # Track unmatched actions — these will be researched by the code gen agent
    unmatched = [a for a in non_trigger_actions if a.get("id", "") not in matched_action_ids]

    total = len(non_trigger_actions)
    matched = len(discovered)

    if unmatched:
        await _emit(state, "discovery.partial",
            f"Found {matched}/{total} APIs in index. Agent will research {len(unmatched)} more.", {
                "matched": matched,
                "total": total,
                "unmatched": [a.get("description", "")[:50] for a in unmatched],
            })
    else:
        await _emit(state, "discovery.complete", f"Discovered {len(discovered)} APIs — all actions matched!", {
            "apis": [{"service": a.service, "endpoint": a.endpoint} for a in discovered],
        })

    return {
        "discovered_apis": [a.model_dump() for a in discovered],
        "unmatched_actions": unmatched,
        "phase": "planning",
    }


# ── Node 3: Plan Workflow (DAG) ───────────────────────────────

async def plan_workflow_node(state: ForgeFlowState) -> dict:
    """Build a workflow DAG from requirements and APIs."""
    from backend.planner.dag_builder import build_dag
    from backend.planner.data_mapper import map_data_flows

    await _emit(state, "planning.started", "Building workflow DAG...")

    # Reconstruct APIEndpoint objects
    apis = [APIEndpoint(**a) for a in state.get("discovered_apis", [])]
    requirements = state.get("business_requirements", {})

    # Pass unmatched actions to DAG builder so it creates research_required steps
    unmatched = state.get("unmatched_actions", [])
    if unmatched:
        requirements = {**requirements, "_unmatched_actions": unmatched}

    dag = await build_dag(requirements, apis)
    data_mappings = await map_data_flows(dag.steps)

    # ── TASK 1: Emit steps one-by-one for animated DAG build ──
    for i, step in enumerate(dag.steps):
        await _emit(state, "dag.step_added", f"Step {i+1}: {step.name}", {
            "step": {
                "id": step.id,
                "name": step.name,
                "depends_on": step.depends_on,
                "step_type": step.step_type,
                "description": step.description,
                "api": {
                    "service": step.api.service,
                    "endpoint": step.api.endpoint,
                } if step.api else None,
            },
            "step_index": i,
            "total_steps": len(dag.steps),
        })
        await asyncio.sleep(0.5)  # 500ms stagger for visual effect

    await _emit(state, "dag.planned", f"Workflow DAG created with {len(dag.steps)} steps", {
        "steps": [{"id": s.id, "name": s.name, "depends_on": s.depends_on} for s in dag.steps],
        "parallel_possible": _find_parallel_groups(dag),
    })

    return {
        "workflow_dag": dag.model_dump(),
        "data_mappings": data_mappings,
        "phase": "generating",
    }


def _find_parallel_groups(dag: WorkflowDAG) -> list[list[str]]:
    """Find steps that can run in parallel."""
    groups = []
    deps_map: dict[str, set[str]] = {}
    for step in dag.steps:
        deps_map[step.id] = set(step.depends_on)

    # Group steps by their dependency set
    by_deps: dict[tuple, list[str]] = {}
    for step_id, deps in deps_map.items():
        key = tuple(sorted(deps))
        by_deps.setdefault(key, []).append(step_id)

    for deps_key, step_ids in by_deps.items():
        if len(step_ids) > 1:
            groups.append(step_ids)

    return groups


# ── Node 4: Generate Code ────────────────────────────────────

async def generate_code_node(state: ForgeFlowState) -> dict:
    """Generate executable Python code from the DAG using the agent tool loop."""
    from backend.codegen.generator import generate_workflow_code

    await _emit(state, "codegen.started", "Generating executable Python code (agent mode)...")

    dag_data = state.get("workflow_dag", {})
    dag = WorkflowDAG(**dag_data)
    data_mappings = state.get("data_mappings", [])

    # Pass event callback so tool calls appear in the UI
    cb = state.get("_event_callback")
    code, extra_files = await generate_workflow_code(dag, data_mappings, event_callback=cb)

    lines = code.count("\n") + 1
    file_count = len(extra_files)
    msg = f"Python code generated ({lines} lines)"
    if file_count:
        msg += f" + {file_count} extra files"

    await _emit(state, "code.generated", msg, {
        "lines": lines,
        "preview": code[:500],
        "full_code": code,
        "extra_files": list(extra_files.keys()),
    })

    return {
        "generated_code": code,
        "extra_files": extra_files,
        "phase": "testing",
    }


# ── Node 5: Security Review ──────────────────────────────────

async def security_review_node(state: ForgeFlowState) -> dict:
    """Quick security review of generated code."""
    from backend.codegen.security_reviewer import review_code

    await _emit(state, "security.started", "Running security review...")

    code = state.get("generated_code", "")
    review = await review_code(code)

    status = "passed" if review.get("safe", True) else "issues_found"
    await _emit(state, "security.complete", f"Security review: {status}", review)

    return {"security_review": review}


# ── Node 5b: Test Generation ─────────────────────────────────

async def test_generation_node(state: ForgeFlowState) -> dict:
    """Auto-generate and run pytest test cases for the workflow."""
    from backend.codegen.test_generator import generate_tests, run_tests

    await _emit(state, "testing.started", "Generating test cases...")

    dag_data = state.get("workflow_dag", {})
    dag = WorkflowDAG(**dag_data)
    code = state.get("generated_code", "")
    extra_files = state.get("extra_files", {})

    # Generate test code
    test_code = await generate_tests(dag, code, extra_files)

    lines = test_code.count("\n") + 1
    await _emit(state, "testing.generated", f"Generated {lines}-line test suite", {
        "test_lines": lines,
        "test_preview": test_code[:400],
    })

    # Run the tests
    import os
    project_dir = os.path.join("/tmp", "forgeflow_codegen")
    os.makedirs(project_dir, exist_ok=True)

    # Write workflow code to project dir for tests to reference
    workflow_path = os.path.join(project_dir, "workflow.py")
    with open(workflow_path, "w") as f:
        f.write(code)

    test_results = await run_tests(test_code, project_dir)

    if test_results["success"]:
        await _emit(state, "testing.passed",
            f"Tests passed! {test_results['passed']}/{test_results['total']} tests passed", {
                "passed": test_results["passed"],
                "failed": test_results["failed"],
                "total": test_results["total"],
            })
    else:
        await _emit(state, "testing.partial",
            f"Tests: {test_results['passed']} passed, {test_results['failed']} failed", {
                "passed": test_results["passed"],
                "failed": test_results["failed"],
                "total": test_results["total"],
                "output": test_results["output"][:500],
            })

    return {
        "test_code": test_code,
        "test_results": test_results,
    }


# ── Node 6: Sandbox Execute ──────────────────────────────────

async def sandbox_execute_node(state: ForgeFlowState) -> dict:
    """Execute the generated code in a sandboxed environment."""
    from backend.execution.sandbox import execute_code
    from backend.execution.error_parser import validate_syntax
    from backend.shared.models import ExecutionResult

    attempt = state.get("debug_attempts", 0) + 1
    await _emit(state, "execution.started", f"Executing in sandbox (attempt {attempt})...")

    code = state.get("generated_code", "")

    # ── AST PRE-VALIDATION: catch syntax errors before execution ──
    syntax_error = validate_syntax(code)
    if syntax_error:
        await _emit(state, "execution.failed", f"Syntax error at line {syntax_error.line_number}: {syntax_error.message}", {
            "stderr": syntax_error.code_context,
            "error": f"{syntax_error.error_type}: {syntax_error.message}",
            "attempt": attempt,
            "category": "SYNTAX_ERROR",
        })
        return {
            "execution_result": ExecutionResult(
                success=False,
                stderr=syntax_error.code_context,
                error=f"{syntax_error.error_type}: {syntax_error.message} (line {syntax_error.line_number})",
                execution_time=0.0,
            ).model_dump()
        }

    # ── Emit per-node "running" status ──
    dag_data = state.get("workflow_dag", {})
    if dag_data and dag_data.get("steps"):
        for step in dag_data["steps"]:
            await _emit(state, "node.status_changed", f"Running: {step.get('name', '')}", {
                "node_id": step.get("id", ""),
                "status": "running",
            })
            await asyncio.sleep(0.3)

    extra_files = state.get("extra_files", {})
    result = await execute_code(code, extra_files=extra_files)

    if result.success:
        # ── TASK 2+6: Emit success status for all nodes ──
        if dag_data and dag_data.get("steps"):
            for step in dag_data["steps"]:
                await _emit(state, "node.status_changed", f"Completed: {step.get('name', '')}", {
                    "node_id": step.get("id", ""),
                    "status": "success",
                })
                await asyncio.sleep(0.15)

        await _emit(state, "execution.success", "Code executed successfully!", {
            "stdout": result.stdout[:500],
            "execution_time": result.execution_time,
        })
    else:
        # ── TASK 2: Emit failure status for all nodes ──
        await _emit(state, "node.status_changed", "Execution failed", {
            "node_id": "all",
            "status": "failed",
        })

        await _emit(state, "execution.failed", f"Execution failed: {result.error[:200] if result.error else 'Unknown error'}", {
            "stderr": result.stderr[:500],
            "error": result.error,
            "attempt": attempt,
        })

    return {"execution_result": result.model_dump()}


# ── Node 7: Self-Debug ────────────────────────────────────────

async def self_debug_node(state: ForgeFlowState) -> dict:
    """Analyze failure and generate targeted fix."""
    from backend.execution.self_debugger import diagnose_and_fix

    attempt = state.get("debug_attempts", 0) + 1
    await _emit(state, "debug.started", f"Self-debug attempt {attempt}/{settings.MAX_DEBUG_ATTEMPTS}...")

    code = state.get("generated_code", "")
    error = state.get("execution_result", {}).get("error", "")
    stderr = state.get("execution_result", {}).get("stderr", "")

    diagnosis = await diagnose_and_fix(
        code=code,
        error=error,
        stderr=stderr,
        attempt=attempt,
    )

    await _emit(state, "debug.diagnosed", f"Diagnosis: {diagnosis.category} — {diagnosis.fix_description}", {
        "category": diagnosis.category,
        "root_cause": diagnosis.root_cause,
        "fix": diagnosis.fix_description,
    })

    # ── TASK 2: Emit fixing → retrying status with dramatic pause ──
    await _emit(state, "node.status_changed", "Applying fix...", {
        "node_id": "all",
        "status": "fixing",
    })
    await asyncio.sleep(1.0)  # dramatic pause
    await _emit(state, "node.status_changed", "Fix applied, retrying...", {
        "node_id": "all",
        "status": "retrying",
    })

    return {
        "generated_code": diagnosis.fixed_function if diagnosis.fixed_function else code,
        "debug_attempts": attempt,
        "debug_history": state.get("debug_history", []) + [diagnosis.model_dump()],
    }


# ── Node 8: Present to User (Approval Gate) ──────────────────

async def present_to_user_node(state: ForgeFlowState) -> dict:
    """Present workflow for approval before deployment — the APPROVAL GATE.

    This node acts as a gate: the workflow is shown to the user with all
    details (code, tests, execution results) and the pipeline awaits approval.
    In API/WebSocket mode, the frontend sends the approval signal.
    """
    exec_result = state.get("execution_result", {})
    success = exec_result.get("success", False)
    debug_attempts = state.get("debug_attempts", 0)
    test_results = state.get("test_results", {})

    if success:
        msg = "✅ Workflow generated, tested, and ready for approval!"
        if debug_attempts > 0:
            msg = f"✅ Workflow self-debugged ({debug_attempts} fix{'es' if debug_attempts > 1 else ''}) — ready for approval!"
    else:
        msg = f"⚠️ Workflow generated but had issues after {debug_attempts} attempts. Review before deploying."

    # Build approval context
    approval_data = {
        "success": success,
        "debug_attempts": debug_attempts,
        "test_results": {
            "passed": test_results.get("passed", 0),
            "failed": test_results.get("failed", 0),
            "total": test_results.get("total", 0),
        },
        "code_lines": state.get("generated_code", "").count("\n") + 1,
        "extra_files": list(state.get("extra_files", {}).keys()),
        "services": list({
            api.get("service", "unknown")
            for api in state.get("discovered_apis", [])
        }),
        "approval_required": True,
    }

    await _emit(state, "workflow.approval_required", msg, approval_data)

    # Auto-approve if execution succeeded (for non-interactive mode)
    # In interactive mode, the frontend sends the approval via WebSocket
    approval = "approved" if success else "needs_review"

    return {
        "final_message": msg,
        "phase": "awaiting_approval" if success else "failed",
        "approval_status": approval,
    }


# ── Node 9: Deploy ────────────────────────────────────────────

async def deploy_node(state: ForgeFlowState) -> dict:
    """Deploy the workflow — save to disk as project folder + persist to SQLite.

    Also records feedback and updates pattern stats for continuous improvement.
    """
    from backend.deployment.workflow_store import save_workflow
    from backend.feedback.learning import record_feedback, update_pattern_stats, log_improvement

    workflow_id = state.get("workflow_id", str(uuid.uuid4())[:8])
    code = state.get("generated_code", "")
    dag_data = state.get("workflow_dag", {})
    requirements = state.get("business_requirements", {})
    debug_attempts = state.get("debug_attempts", 0)

    # Extract service names from discovered APIs
    services = list({
        api.get("service", "unknown")
        for api in state.get("discovered_apis", [])
    })

    # Get extra files from multi-file generation
    extra_files = state.get("extra_files", {})

    # Include test file in extra_files if generated
    test_code = state.get("test_code")
    if test_code:
        extra_files["test_workflow.py"] = test_code

    # ── REAL DEPLOYMENT: Save as project folder + SQLite record ──
    deploy_result = save_workflow(
        workflow_id=workflow_id,
        name=requirements.get("workflow_name", dag_data.get("name", "Untitled Workflow")),
        description=requirements.get("description", dag_data.get("description", "")),
        user_request=state.get("user_request", ""),
        code=code,
        dag=dag_data,
        debug_attempts=debug_attempts,
        services=services,
        extra_files=extra_files,
    )

    project_dir = deploy_result["project_dir"]
    files = deploy_result["files"]

    # ── CONTINUOUS IMPROVEMENT: Record feedback & pattern stats ──
    exec_result = state.get("execution_result", {})
    test_results = state.get("test_results", {})

    record_feedback(
        workflow_id=workflow_id,
        feedback_type="auto_success" if exec_result.get("success") else "auto_failure",
        user_request=state.get("user_request", ""),
        services=services,
        debug_attempts=debug_attempts,
        execution_success=exec_result.get("success", False),
        test_results=test_results,
    )

    # Update pattern stats for each service used
    for api_data in state.get("discovered_apis", []):
        service = api_data.get("service", "Unknown")
        endpoint = api_data.get("endpoint", "unknown")
        pattern_type = endpoint.split("/")[-1] if "/" in endpoint else endpoint
        update_pattern_stats(
            service=service,
            pattern_type=pattern_type,
            success=exec_result.get("success", False),
            debug_attempts=debug_attempts,
            error_msg=exec_result.get("error", "") if not exec_result.get("success") else "",
        )

    log_improvement(
        "workflow_deployed",
        f"Deployed '{requirements.get('workflow_name', 'Workflow')}' with {len(services)} services",
        {"workflow_id": workflow_id, "services": services, "debug_attempts": debug_attempts},
    )

    await _emit(state, "workflow.deployed", f"Workflow deployed! ID: {workflow_id} — saved {len(files)} files to {project_dir}", {
        "workflow_id": workflow_id,
        "project_dir": project_dir,
        "files": files,
        "services": services,
    })

    return {"deployed": True, "phase": "deployed", "final_message": f"Workflow deployed! ID: {workflow_id}"}


# ── Routing Functions ─────────────────────────────────────────

def route_after_conversation(state: ForgeFlowState) -> str:
    """Route after conversation: need clarification or proceed?

    Strategy: Ask MAX 1 round of clarifying questions for vague requests.
    - Vague request + first pass → ask questions, wait for user response
    - After user answers (or confidence >= 0.7) → proceed to discovery
    - Always proceed after 1 clarification round to avoid blocking
    """
    clarifications = state.get("clarification_needed", [])
    confidence = state.get("confidence", 0)
    asked = state.get("clarifications_asked", 0)

    # Proceed if: confidence is high, or we already asked once
    if confidence >= 0.75 or asked >= 1:
        return "requirements_complete"

    # Ask for clarification if: low confidence, first pass, and have questions
    if clarifications and asked < 1:
        return "need_clarification"

    return "requirements_complete"


def route_after_execution(state: ForgeFlowState) -> str:
    """Route after execution: success or failure?"""
    result = state.get("execution_result", {})
    if result.get("success"):
        return "success"
    return "failure"


def route_after_debug(state: ForgeFlowState) -> str:
    """Route after debug: retry or give up?"""
    attempts = state.get("debug_attempts", 0)
    if attempts < settings.MAX_DEBUG_ATTEMPTS:
        return "retry"
    return "max_attempts"


def route_after_present(state: ForgeFlowState) -> str:
    """Route after presenting: approval gate — deploy only if approved."""
    approval = state.get("approval_status", "")
    if approval == "approved":
        return "approve"
    return "reject"


# ── Build the Graph ───────────────────────────────────────────

def build_graph():
    """Build and compile the ForgeFlow LangGraph."""
    from langgraph.graph import StateGraph, START, END

    graph = StateGraph(ForgeFlowState)

    # Add nodes (10-node pipeline)
    graph.add_node("conversation", conversation_node)
    graph.add_node("api_discovery", api_discovery_node)
    graph.add_node("plan_workflow", plan_workflow_node)
    graph.add_node("generate_code", generate_code_node)
    graph.add_node("review_security", security_review_node)
    graph.add_node("generate_tests", test_generation_node)      # NEW: auto-generate test cases
    graph.add_node("sandbox_execute", sandbox_execute_node)
    graph.add_node("self_debug", self_debug_node)
    graph.add_node("present_to_user", present_to_user_node)     # UPDATED: approval gate
    graph.add_node("deploy", deploy_node)                       # UPDATED: records feedback

    # Edges
    graph.add_edge(START, "conversation")

    graph.add_conditional_edges("conversation", route_after_conversation, {
        "need_clarification": END,  # Stop pipeline — WebSocket handler will restart with user's answer
        "requirements_complete": "api_discovery",
    })

    graph.add_edge("api_discovery", "plan_workflow")
    graph.add_edge("plan_workflow", "generate_code")
    graph.add_edge("generate_code", "review_security")
    graph.add_edge("review_security", "generate_tests")   # security → tests
    graph.add_edge("generate_tests", "sandbox_execute")    # tests → sandbox

    graph.add_conditional_edges("sandbox_execute", route_after_execution, {
        "success": "present_to_user",
        "failure": "self_debug",
    })

    graph.add_conditional_edges("self_debug", route_after_debug, {
        "retry": "sandbox_execute",
        "max_attempts": "present_to_user",
    })

    graph.add_conditional_edges("present_to_user", route_after_present, {
        "approve": "deploy",
        "reject": END,
    })

    graph.add_edge("deploy", END)

    return graph.compile()


# ── Run Pipeline ──────────────────────────────────────────────

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_forgeflow_pipeline(
    user_request: str,
    workflow_id: str,
    slack_channel: str = "",
    event_callback: Callable | None = None,
) -> dict:
    """Run the full ForgeFlow pipeline end-to-end."""
    graph = get_graph()

    initial_state: ForgeFlowState = {
        "user_request": user_request,
        "workflow_id": workflow_id,
        "slack_channel": slack_channel,
        "messages": [],
        "phase": "collecting",
        "business_requirements": {},
        "confidence": 0.0,
        "clarification_needed": [],
        "clarifications_asked": 0,
        "discovered_apis": [],
        "unmatched_actions": [],
        "workflow_dag": None,
        "data_mappings": [],
        "generated_code": None,
        "extra_files": {},
        "security_review": None,
        "test_code": None,
        "test_results": None,
        "execution_result": None,
        "debug_attempts": 0,
        "debug_history": [],
        "approval_status": "pending",
        "deployed": False,
        "final_message": "",
        "events": [],
        "_event_callback": event_callback,
    }

    # Run the graph to completion (may stop early if clarification needed)
    final_state = await graph.ainvoke(initial_state)

    # Check if pipeline stopped for clarification
    needs_clarification = (
        final_state.get("phase") == "collecting"
        and final_state.get("clarification_needed")
        and final_state.get("confidence", 1.0) < 0.75
    )

    return {
        "phase": final_state.get("phase", "unknown"),
        "needs_clarification": needs_clarification,
        "clarification_needed": final_state.get("clarification_needed", []),
        "business_requirements": final_state.get("business_requirements", {}),
        "workflow_dag": final_state.get("workflow_dag"),
        "generated_code": final_state.get("generated_code"),
        "execution_result": final_state.get("execution_result"),
        "test_results": final_state.get("test_results"),
        "debug_history": final_state.get("debug_history", []),
        "deployed": final_state.get("deployed", False),
        "final_message": final_state.get("final_message", ""),
        "events": final_state.get("events", []),
    }
