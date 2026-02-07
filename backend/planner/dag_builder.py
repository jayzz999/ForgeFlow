"""Build workflow DAG from requirements and discovered APIs."""

import json
import uuid

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json
from backend.shared.models import WorkflowDAG, WorkflowStep, APIEndpoint


async def build_dag(
    requirements: dict,
    discovered_apis: list[APIEndpoint],
) -> WorkflowDAG:
    """Build a WorkflowDAG from requirements and discovered APIs."""
    apis_info = []
    for api in discovered_apis:
        apis_info.append({
            "service": api.service,
            "endpoint": api.endpoint,
            "method": api.method,
            "description": api.description,
            "parameters": api.parameters,
            "auth_type": api.auth_type.value,
        })

    system = """You are ForgeFlow's workflow planner. Build an execution DAG from requirements and discovered APIs.

RULES:
1. Each step should map to a REAL operation (API call, HTTP request, data processing)
2. Identify steps that can run in PARALLEL (no dependencies between them)
3. Map data flow between steps (what data passes from one step to the next)
4. Include a trigger step as the first step
5. Add error handling strategy for each step
6. For steps WITH a matching discovered API: use api_index to reference it
7. For steps WITHOUT a matching API: set api_index to null, set research_required to true, and include api_hint with service info and docs URL
8. EVERY step must have a clear, specific description of what it does — never use vague descriptions

API HINT FORMAT (for steps without pre-indexed APIs):
When api_index is null, include this in inputs:
"api_hint": {"service": "Gmail", "docs_url": "https://developers.google.com/gmail/api/reference/rest", "likely_endpoint": "POST /gmail/v1/users/me/messages/send", "auth_type": "oauth2"}

The code generation agent has web browsing tools and will research these APIs automatically.

OUTPUT ONLY valid JSON:
{
    "name": "workflow name",
    "description": "one-line description",
    "trigger": {"type": "manual|webhook|schedule|event", "description": "..."},
    "steps": [
        {
            "id": "step_1",
            "name": "Human-readable step name",
            "description": "What this step does — be specific",
            "step_type": "trigger|api_call|condition|delay",
            "api_index": 0,
            "research_required": false,
            "inputs": {"param_name": "source (trigger.field, step_1.output.field, or literal)"},
            "outputs": {"field_name": "description of output"},
            "depends_on": [],
            "error_handling": "retry_3x|fallback|abort",
            "condition": null
        }
    ],
    "environment_vars": ["VAR_NAME_1", "VAR_NAME_2"],
    "parallel_groups": [["step_2", "step_3"]]
}"""

    # Include unmatched actions context if available
    unmatched_info = ""
    unmatched = requirements.get("_unmatched_actions", [])
    if unmatched:
        unmatched_info = (
            f"\n\nUNMATCHED ACTIONS (no pre-indexed API — set research_required=true for these):\n"
            f"{json.dumps(unmatched, indent=2)}\n"
            f"For each unmatched action, include an api_hint in inputs with service, docs_url, likely_endpoint, and auth_type."
        )

    prompt = (
        f"REQUIREMENTS:\n{json.dumps(requirements, indent=2)}\n\n"
        f"DISCOVERED APIs:\n{json.dumps(apis_info, indent=2)}"
        f"{unmatched_info}"
    )

    try:
        plan = await generate_json(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=4000,
        )
    except Exception:
        return _build_fallback_dag(requirements, discovered_apis)

    if not plan:
        return _build_fallback_dag(requirements, discovered_apis)

    # Convert to WorkflowDAG model
    steps = []
    for s in plan.get("steps", []):
        api = None
        api_idx = s.get("api_index")
        if api_idx is not None and 0 <= api_idx < len(discovered_apis):
            api = discovered_apis[api_idx]

        steps.append(WorkflowStep(
            id=s.get("id", f"step_{len(steps)+1}"),
            name=s.get("name", "Unnamed Step"),
            description=s.get("description", ""),
            api=api,
            inputs=s.get("inputs", {}),
            outputs=s.get("outputs", {}),
            depends_on=s.get("depends_on", []),
            error_handling=s.get("error_handling", "retry_3x"),
            condition=s.get("condition"),
            step_type=s.get("step_type", "api_call"),
        ))

    return WorkflowDAG(
        id=str(uuid.uuid4())[:8],
        name=plan.get("name", requirements.get("workflow_name", "Workflow")),
        description=plan.get("description", requirements.get("description", "")),
        trigger=plan.get("trigger", {"type": "manual"}),
        steps=steps,
        environment_vars=plan.get("environment_vars", []),
    )


def _build_fallback_dag(requirements: dict, apis: list[APIEndpoint]) -> WorkflowDAG:
    """Build a simple sequential DAG as fallback."""
    steps = []
    for i, action in enumerate(requirements.get("actions", [])):
        api = apis[i] if i < len(apis) else None
        depends = [f"step_{i}"] if i > 0 else []
        steps.append(WorkflowStep(
            id=f"step_{i+1}",
            name=action.get("description", f"Step {i+1}")[:50],
            description=action.get("description", ""),
            api=api,
            depends_on=depends,
            step_type="trigger" if action.get("is_trigger") else "api_call",
        ))

    return WorkflowDAG(
        id=str(uuid.uuid4())[:8],
        name=requirements.get("workflow_name", "Workflow"),
        description=requirements.get("description", ""),
        trigger={"type": "manual"},
        steps=steps,
    )
