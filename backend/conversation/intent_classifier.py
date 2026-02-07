"""Fast intent classification using Gemini."""

import json

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json


INTENT_TYPES = [
    "trading_alert",     # Price monitoring, trading signals, market data
    "notification",      # Sending messages via email/slack/sms
    "data_pipeline",     # ETL, data transformation, synchronization
    "approval_flow",     # Request/approval chains
    "onboarding",        # User/employee setup processes
    "monitoring",        # System/metric monitoring and alerting
    "custom",            # Other automation needs
]


async def classify_intent(user_message: str) -> dict:
    """Classify user intent quickly using Gemini.

    Returns:
        {"intent": str, "confidence": float, "is_modification": bool, "is_status_check": bool}
    """
    system = f"""Classify the user's request into one of these workflow types:
{json.dumps(INTENT_TYPES)}

Also determine:
- is_modification: true if user wants to modify an existing workflow
- is_status_check: true if user is asking about workflow status

Output ONLY valid JSON:
{{"intent": "...", "confidence": 0.0-1.0, "is_modification": false, "is_status_check": false}}"""

    try:
        result = await generate_json(
            prompt=user_message,
            system=system,
            model=settings.GEMINI_FAST_MODEL,
            max_tokens=100,
        )
        if result:
            return result
    except Exception:
        pass

    return {
        "intent": "custom",
        "confidence": 0.5,
        "is_modification": False,
        "is_status_check": False,
    }
