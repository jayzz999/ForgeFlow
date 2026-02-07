"""LLM-powered API selection and reranking from vector search results."""

import json

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json
from backend.shared.models import APIEndpoint, AuthType


async def select_best_api(
    action_description: str,
    candidates: list[dict],
    workflow_context: str = "",
) -> APIEndpoint | None:
    """Use LLM to select the best API from vector search candidates."""
    if not candidates:
        return None

    candidates_text = ""
    for i, c in enumerate(candidates):
        meta = c.get("metadata", {})
        candidates_text += (
            f"\n--- Candidate {i+1} (confidence: {c.get('confidence', 0)}) ---\n"
            f"Service: {meta.get('service', 'Unknown')}\n"
            f"Endpoint: {meta.get('method', '')} {meta.get('endpoint', '')}\n"
            f"Summary: {meta.get('summary', '')}\n"
            f"Parameters: {meta.get('params_json', '')}\n"
            f"Auth: {meta.get('auth_type', 'unknown')}\n"
        )

    system = (
        "You are an API selection expert. Given a workflow step description "
        "and candidate API endpoints from a vector search, select the BEST "
        "matching API. Consider semantic match, parameter availability, and "
        "authentication requirements.\n\n"
        "Output ONLY valid JSON with these fields:\n"
        '{"selected_index": <0-based index>, "service": "...", "endpoint": "...", '
        '"method": "...", "confidence": 0.0-1.0, "reasoning": "...", '
        '"parameter_mapping": {"param_name": "source_description"}}'
    )

    prompt = (
        f"STEP DESCRIPTION: {action_description}\n\n"
        f"WORKFLOW CONTEXT: {workflow_context}\n\n"
        f"CANDIDATE APIs:{candidates_text}"
    )

    try:
        result = await generate_json(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_FAST_MODEL,
        )
    except Exception:
        # Fallback: use highest confidence candidate
        best = max(candidates, key=lambda c: c.get("confidence", 0))
        meta = best.get("metadata", {})
        return APIEndpoint(
            service=meta.get("service", "Unknown"),
            endpoint=meta.get("endpoint", ""),
            method=meta.get("method", "POST"),
            description=meta.get("summary", ""),
            auth_type=_parse_auth(meta.get("auth_type", "none")),
            base_url=meta.get("base_url", ""),
            confidence=best.get("confidence", 0.5),
        )

    idx = result.get("selected_index", 0)
    if idx >= len(candidates):
        idx = 0

    meta = candidates[idx].get("metadata", {})
    req_schema = meta.get("request_schema", "{}")

    # Extract parameters from request schema
    params = []
    try:
        schema = json.loads(req_schema)
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for name, details in props.items():
            params.append({
                "name": name,
                "type": details.get("type", "string"),
                "required": name in required,
                "description": details.get("description", ""),
            })
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"[APISelector] Schema parse warning: {e}")

    return APIEndpoint(
        service=result.get("service", meta.get("service", "Unknown")),
        endpoint=result.get("endpoint", meta.get("endpoint", "")),
        method=result.get("method", meta.get("method", "POST")),
        description=meta.get("summary", ""),
        parameters=params,
        auth_type=_parse_auth(meta.get("auth_type", "none")),
        base_url=meta.get("base_url", ""),
        confidence=result.get("confidence", 0.8),
    )


def _parse_auth(auth_str: str) -> AuthType:
    """Parse auth string to AuthType enum."""
    auth_lower = auth_str.lower()
    if "bearer" in auth_lower:
        return AuthType.BEARER
    if "oauth" in auth_lower:
        return AuthType.OAUTH2
    if "api" in auth_lower and "key" in auth_lower:
        return AuthType.API_KEY
    if "websocket" in auth_lower:
        return AuthType.WEBSOCKET_TOKEN
    if auth_lower == "none":
        return AuthType.NONE
    return AuthType.API_KEY


async def extract_actions(user_request: str) -> list[dict]:
    """Extract individual action intents from a user's workflow description."""
    system = (
        "You are a workflow analyzer. Extract CONCRETE, SPECIFIC API actions from a "
        "business workflow description. Each action should map to a real API call.\n\n"
        "RULES:\n"
        "1. ALWAYS extract at least 3 concrete actions, even for vague requests\n"
        "2. Each action must specify a real service (Slack, Gmail, Jira, Google Sheets, HTTP, etc.)\n"
        "3. Descriptions must be specific enough to search for an API endpoint\n"
        "4. NEVER use generic descriptions like 'process data' — specify exactly what service and what operation\n\n"
        "EXAMPLES:\n"
        "- 'automate onboarding' → create Jira ticket, send Gmail welcome email, invite to Slack channels, add Google Sheets row\n"
        "- 'monitor website' → HTTP GET health check, log to Google Sheets, send Slack alert, create Jira incident\n\n"
        "Output ONLY valid JSON with an 'actions' key containing an array:\n"
        '{"actions": [{"id": "step_1", "description": "specific API action with service name", '
        '"service_hint": "Slack|Gmail|Jira|Google Sheets|HTTP|Deriv|SMTP", '
        '"api_type": "rest|websocket|email|http_check", '
        '"depends_on": [], "is_trigger": false}]}'
    )

    try:
        result = await generate_json(
            prompt=user_request,
            system=system,
            model=settings.GEMINI_FAST_MODEL,
            max_tokens=3000,
        )
        if isinstance(result, dict) and "actions" in result:
            return result["actions"]
        if isinstance(result, dict) and "steps" in result:
            return result["steps"]
        if isinstance(result, list):
            return result
        for v in result.values():
            if isinstance(v, list):
                return v
        return []
    except Exception:
        return []
