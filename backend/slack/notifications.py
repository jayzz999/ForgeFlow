"""Slack notification system — streams pipeline events to Slack channels."""

import logging

from slack_sdk.web.async_client import AsyncWebClient

from backend.shared.config import settings

logger = logging.getLogger("forgeflow.slack.notifications")


async def send_slack_message(channel: str, text: str):
    """Send a simple text message to a Slack channel."""
    if not settings.SLACK_BOT_TOKEN:
        logger.debug(f"[Slack disabled] {text}")
        return

    try:
        client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
        await client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")


async def send_slack_rich_message(channel: str, blocks: list[dict], text: str = ""):
    """Send a rich Block Kit message to Slack."""
    if not settings.SLACK_BOT_TOKEN:
        return

    try:
        client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
        await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=text or "ForgeFlow notification",
        )
    except Exception as e:
        logger.error(f"Failed to send Slack blocks: {e}")


# ── Event Bus Listener ────────────────────────────────────────

# Event type -> emoji + formatting
EVENT_CONFIG = {
    "workflow.created": {"emoji": ":rocket:", "bold": True},
    "conversation.analyzed": {"emoji": ":brain:", "bold": False},
    "api.discovered": {"emoji": ":mag:", "bold": False},
    "discovery.complete": {"emoji": ":telescope:", "bold": True},
    "dag.planned": {"emoji": ":deciduous_tree:", "bold": True},
    "code.generated": {"emoji": ":computer:", "bold": True},
    "security.complete": {"emoji": ":shield:", "bold": False},
    "execution.started": {"emoji": ":hourglass_flowing_sand:", "bold": False},
    "execution.success": {"emoji": ":white_check_mark:", "bold": True},
    "execution.failed": {"emoji": ":x:", "bold": True},
    "debug.started": {"emoji": ":wrench:", "bold": True},
    "debug.diagnosed": {"emoji": ":stethoscope:", "bold": True},
    "workflow.ready": {"emoji": ":checkered_flag:", "bold": True},
    "workflow.deployed": {"emoji": ":tada:", "bold": True},
}

# Only send these events to avoid channel spam
BROADCAST_EVENTS = {
    "workflow.created",
    "discovery.complete",
    "dag.planned",
    "code.generated",
    "execution.success",
    "execution.failed",
    "debug.started",
    "debug.diagnosed",
    "workflow.deployed",
}


async def slack_event_listener(event: dict):
    """Listen for pipeline events and forward to Slack notification channel.

    This is registered as an event listener on the main event bus.
    """
    event_type = event.get("event_type", "")

    if event_type not in BROADCAST_EVENTS:
        return

    channel = settings.SLACK_NOTIFICATION_CHANNEL
    if not channel:
        return

    config = EVENT_CONFIG.get(event_type, {"emoji": ":gear:", "bold": False})
    message = event.get("message", "")
    workflow_id = event.get("workflow_id", "")

    if config["bold"]:
        text = f"{config['emoji']} *[{workflow_id}]* {message}"
    else:
        text = f"{config['emoji']} [{workflow_id}] {message}"

    # Add details for specific events
    data = event.get("data", {})
    if event_type == "discovery.complete" and data.get("apis"):
        apis = data["apis"]
        api_list = "\n".join([f"  - {a.get('service', '')} ({a.get('endpoint', '')})" for a in apis])
        text += f"\n{api_list}"

    if event_type == "debug.diagnosed":
        text += f"\n  Category: `{data.get('category', '')}`"
        text += f"\n  Root cause: {data.get('root_cause', '')}"

    await send_slack_message(channel, text)
