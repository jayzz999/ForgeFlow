"""Map data flow between workflow steps."""

import json

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json
from backend.shared.models import WorkflowStep


async def map_data_flows(steps: list[WorkflowStep]) -> list[dict]:
    """Generate data mappings between dependent workflow steps.

    Maps data flow even for steps without pre-indexed APIs — uses step
    descriptions and inferred outputs to create meaningful mappings.
    """
    mappings = []

    for step in steps:
        if not step.depends_on:
            continue

        # Find the source steps — include ALL sources, not just those with APIs
        source_steps = [s for s in steps if s.id in step.depends_on]
        if not source_steps:
            continue

        sources_info = []
        for src in source_steps:
            src_info = {
                "step_id": src.id,
                "name": src.name,
                "description": src.description,
                "outputs": src.outputs,
            }
            if src.api:
                src_info["service"] = src.api.service
                src_info["endpoint"] = src.api.endpoint
            else:
                src_info["service"] = "(to be researched)"
                src_info["endpoint"] = "(to be researched)"
            sources_info.append(src_info)

        system = """You map data between workflow steps. Given source step outputs and target step inputs, generate a Python dict mapping expression.

Even if the exact API schemas are not known, infer reasonable data mappings based on the step descriptions and common API patterns.

CRITICAL: If the step's inputs already contain specific literal values (like channel names, email addresses, or message text),
use those EXACT values in the mapping. Do NOT substitute them with generic defaults like "#general" or "Welcome to the team!".
The user specified those values for a reason.

Output ONLY valid JSON:
{
    "mapping": {"target_param": "f-string or expression using source data"},
    "explanation": "brief description of the mapping"
}"""

        # Build prompt with available info (works with or without APIs)
        if step.api:
            target_info = (
                f"Target service: {step.api.service}\n"
                f"Target endpoint: {step.api.endpoint}\n"
                f"Target parameters: {json.dumps(step.api.parameters)}"
            )
        else:
            target_info = (
                f"Target description: {step.description}\n"
                f"Target inputs: {json.dumps(step.inputs)}"
            )

        prompt = (
            f"SOURCE STEPS:\n{json.dumps(sources_info)}\n\n"
            f"TARGET STEP: {step.name}\n"
            f"TARGET STEP INPUTS (use these exact values): {json.dumps(step.inputs)}\n"
            f"{target_info}"
        )

        try:
            result = await generate_json(
                prompt=prompt,
                system=system,
                model=settings.GEMINI_FAST_MODEL,
                max_tokens=1000,
            )
            if result:
                mappings.append({
                    "from_steps": [s.id for s in source_steps],
                    "to_step": step.id,
                    "mapping": result.get("mapping", {}),
                    "explanation": result.get("explanation", ""),
                })
        except Exception:
            pass

    return mappings
