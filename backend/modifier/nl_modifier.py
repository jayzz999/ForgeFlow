"""Natural language workflow modification — modify existing workflows conversationally."""

import json

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json
from backend.shared.models import WorkflowDAG


async def modify_workflow(
    modification_request: str,
    current_dag: WorkflowDAG,
    current_code: str,
) -> dict:
    """Apply a natural language modification to an existing workflow.

    Returns:
        {"modified_dag": dict, "modified_code": str, "changes": str}
    """
    system = """You are ForgeFlow's workflow modifier. Given a modification request and an existing workflow, generate the updated workflow.

RULES:
1. Only change what's necessary to fulfill the modification
2. Preserve all other workflow functionality
3. If adding a condition, insert a condition node
4. If adding a delay, insert a delay node
5. If changing a threshold, modify the existing node
6. Return the COMPLETE modified code (not just the diff)

OUTPUT ONLY valid JSON:
{
    "changes_description": "what was changed",
    "modified_steps": [...updated steps array...],
    "modified_code": "complete modified Python code",
    "affected_nodes": ["node_ids that changed"]
}"""

    prompt = (
        f"MODIFICATION REQUEST: {modification_request}\n\n"
        f"CURRENT DAG:\n{json.dumps(current_dag.model_dump(), indent=2)}\n\n"
        f"CURRENT CODE:\n```python\n{current_code}\n```"
    )

    try:
        result = await generate_json(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=4000,
        )
        if result:
            return {
                "changes": result.get("changes_description", ""),
                "modified_code": result.get("modified_code", current_code),
                "affected_nodes": result.get("affected_nodes", []),
            }
    except Exception as e:
        print(f"[Modifier] Modification error: {e}")

    return {
        "changes": "Could not parse modification",
        "modified_code": current_code,
        "affected_nodes": [],
    }
