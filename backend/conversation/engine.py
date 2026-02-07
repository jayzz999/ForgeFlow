"""Conversation engine with smart requirement extraction and clarification."""

import json

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json, generate_text


async def extract_requirements(user_request: str, messages: list[dict] | None = None) -> dict:
    """Extract structured business requirements from user input.

    Returns a dict with:
    - intent: workflow type classification
    - entities: services/systems mentioned
    - actions: what needs to happen
    - triggers: what starts the workflow
    - conditions: any conditional logic
    - confidence: how complete the requirements are (0-1)
    - clarification_needed: list of questions if confidence < 0.7
    - assumed_defaults: what was assumed for missing info
    """
    system = """You are ForgeFlow's requirement extractor. Analyze the user's workflow description and extract DETAILED, ACTIONABLE structured requirements.

CRITICAL RULES:
1. ALWAYS decompose the request into 3-8 CONCRETE action steps — even if the user is vague
2. For each action, specify a concrete service_hint (Slack, Gmail, Google Sheets, REST API, HTTP, etc.)
   NOTE: Jira is NOT available. Do NOT suggest Jira. Available services: Slack, Gmail (SMTP), Google Sheets, HTTP/Webhooks, Deriv.
3. If the user doesn't specify services, INFER the most likely ones for their use case
4. For vague requests like "automate X", break down into: data collection, processing, notification, logging, tracking steps
5. Each action description must be specific enough to implement as an API call (e.g., "Send Slack notification to #onboarding channel with welcome message" NOT just "notify team")
6. NEVER return an empty actions list — always infer at least 3 concrete steps

CLARIFICATION RULES (IMPORTANT — READ CAREFULLY):
- You MUST ask clarifying questions when the user hasn't provided SPECIFIC operational details like:
  * Email addresses (who to email, recipient addresses)
  * Slack channel names (which channel to post to, e.g., #onboarding, #general)
  * Task tracking details (Google Sheets row for tracking)
  * Google Sheets spreadsheet IDs or names
  * Specific trigger conditions or schedules
  * Employee data fields or form URLs
- Even if the WORKFLOW TYPE is obvious, the SPECIFICS matter for generating working code.
- ALWAYS ask for the 2 most critical missing specifics. Never skip clarification for vague requests.

VAGUE examples that NEED clarification (confidence 0.5-0.6):
  "automate employee onboarding" → Ask:
    1. "What's the new employee's email and name? (Or should the workflow accept these as inputs?)"
    2. "Which Slack channel should welcome messages go to? (e.g., #onboarding, #general)"
  "set up alerts" → Ask:
    1. "What should be monitored? (URL, API endpoint, database metric?)"
    2. "Where should alerts be sent? (Slack channel name, email address?)"
  "send reports" → Ask:
    1. "What data source should the report pull from?"
    2. "Who should receive it? (email addresses, Slack channel?)"

CLEAR examples that DO NOT need clarification (confidence 0.85+):
  "When V75 moves 2% in 5 min, alert #trading on Slack" → confidence 0.9, no questions
  "Send a Slack message to #general when a Jira ticket is created in PROJ-123" → confidence 0.85
  "Email john@company.com a PDF report from the Sales Google Sheet every Monday" → confidence 0.9

- Questions must be SPECIFIC and actionable. Ask about: email addresses, channel names, project keys, spreadsheet names, trigger conditions
- MAXIMUM 2 clarifying questions. Ask only what's critical to generate a WORKING workflow.
- Even when asking clarification, STILL fill in the actions list with your best guesses and list what you assumed in assumed_defaults

CONFIDENCE SCALE:
  0.3 = barely understandable, cannot infer intent
  0.5 = clear intent but NO specifics (no emails, no channel names, no project keys)
  0.6 = clear intent with SOME specifics but key details missing
  0.75 = clear intent with most specifics provided (channels, emails, etc.)
  0.85 = very specific with services, channels, recipients all mentioned
  0.95 = fully specified including credentials/env var names

DECOMPOSITION EXAMPLES:
- "automate employee onboarding" → confidence: 0.5 (no specifics!), clarification_needed: ["What's the new employee's name and email?", "Which Slack channel should welcome messages go to?"], actions (best guesses):
  1. Send welcome email to new employee via Gmail SMTP (service: Gmail) — assumed email: unknown
  2. Post welcome message to team Slack channel (service: Slack) — assumed channel: unknown
  3. Create tracking row in Google Sheets onboarding spreadsheet (service: Google Sheets)
  4. Send manager notification on Slack with onboarding checklist (service: Slack)
  assumed_defaults: ["Employee email: not specified", "Slack channel: not specified", "Google Sheet ID: not specified"]

- "Send welcome email to john@acme.com, post to #new-hires on Slack, log to Google Sheet 1abc2def" → confidence: 0.85, NO clarification needed, actions:
  1. Send welcome email to john@acme.com (service: Gmail)
  2. Post welcome message to #new-hires (service: Slack)
  3. Log onboarding event to Google Sheet (service: Google Sheets)

- "monitor website uptime" → confidence: 0.5 (missing: which URL, which channel), clarification_needed: ["Which URL should be monitored?", "Where should alerts be sent? (Slack channel, email?)"], actions:
  1. Send HTTP GET health check to target URL (service: HTTP)
  2. Log response status and latency to Google Sheets (service: Google Sheets)
  3. Send Slack alert to #ops channel if status is not 200 (service: Slack)
  4. Send email alert on downtime (service: Gmail)

OUTPUT ONLY valid JSON:
{
    "intent": "trading_alert|notification|data_pipeline|approval_flow|onboarding|monitoring|custom",
    "workflow_name": "descriptive name for the workflow",
    "description": "one-line summary",
    "entities": [{"name": "Slack", "type": "messaging"}, ...],
    "actions": [
        {
            "id": "step_1",
            "description": "specific action description with service details",
            "service_hint": "Slack|Gmail|Jira|Google Sheets|HTTP|Deriv|SMTP|REST API",
            "api_type": "rest|websocket|email|http_check",
            "depends_on": [],
            "is_trigger": false,
            "research_urls": ["https://api.example.com/docs"]
        }
    ],
    "triggers": [{"type": "webhook|schedule|event|manual", "description": "what starts it"}],
    "conditions": [{"description": "conditional logic if any"}],
    "data_flows": [{"from_step": "step_1", "to_step": "step_2", "data": "what data passes"}],
    "confidence": 0.0-1.0,
    "clarification_needed": ["question if confidence < 0.7"],
    "assumed_defaults": ["what was assumed"]
}"""

    # Build context from conversation history
    context = ""
    if messages:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            context += f"{role}: {content}\n"

    prompt = f"{context}user: {user_request}" if context else user_request

    try:
        result = await generate_json(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=4000,
        )
        if result:
            return result
    except Exception as e:
        print(f"[Conversation] Requirement extraction error: {e}")

    return {
        "intent": "custom",
        "workflow_name": "Unknown Workflow",
        "description": user_request[:100],
        "entities": [],
        "actions": [],
        "triggers": [{"type": "manual", "description": "Manual trigger"}],
        "conditions": [],
        "data_flows": [],
        "confidence": 0.3,
        "clarification_needed": ["Could you describe your workflow in more detail?"],
        "assumed_defaults": [],
    }


async def generate_clarification(requirements: dict) -> str:
    """Generate a natural clarification message from missing requirements."""
    questions = requirements.get("clarification_needed", [])
    if not questions:
        return ""

    system = (
        "You are ForgeFlow, a friendly workflow automation assistant. "
        "Generate a brief, natural clarification question. Be concise — "
        "one question max. Show what you already understood and ask only "
        "what's critical."
    )

    prompt = (
        f"Workflow so far: {requirements.get('description', '')}\n"
        f"Missing info: {json.dumps(questions)}\n"
        f"Assumed defaults: {json.dumps(requirements.get('assumed_defaults', []))}\n\n"
        "Generate a brief clarification message."
    )

    try:
        return await generate_text(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_FAST_MODEL,
            temperature=0.7,
            max_tokens=200,
        )
    except Exception:
        return questions[0] if questions else "Could you provide more details?"


async def generate_plan_summary(requirements: dict, discovered_apis: list[dict]) -> str:
    """Generate a user-friendly summary of the planned workflow."""
    system = (
        "You are ForgeFlow. Generate a brief, clear summary of the workflow plan. "
        "Use numbered steps. Mention which APIs were discovered. "
        "End with 'Shall I generate this workflow?' Keep it under 150 words."
    )

    prompt = (
        f"Requirements: {json.dumps(requirements)}\n"
        f"Discovered APIs: {json.dumps([{'service': a.get('service', a.get('metadata', {}).get('service', '')), 'endpoint': a.get('endpoint', a.get('metadata', {}).get('endpoint', ''))} for a in discovered_apis])}"
    )

    try:
        return await generate_text(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_FAST_MODEL,
            temperature=0.5,
            max_tokens=300,
        )
    except Exception:
        return "I've planned your workflow. Shall I generate it?"
