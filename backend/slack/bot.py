"""ForgeFlow Slack Bot — Deep Slack integration.

Three modes:
1. Slack as USER INTERFACE: /forge command + DM the bot
2. Slack as NOTIFICATION CHANNEL: real-time pipeline events
3. Slack as WORKFLOW TARGET: workflows can call Slack API
"""

import asyncio
import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from backend.shared.config import settings

# Enable Slack debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("forgeflow.slack")

# Initialize Slack app
slack_app = AsyncApp(
    token=settings.SLACK_BOT_TOKEN,
    signing_secret=settings.SLACK_SIGNING_SECRET,
    logger=logging.getLogger("slack_bolt"),
)


# ── Slash Command: /forge ─────────────────────────────────────

@slack_app.command("/forge")
async def handle_forge_command(ack, command, say):
    """Handle /forge <workflow description> command."""
    await ack()

    user_id = command.get("user_id", "")
    channel_id = command.get("channel_id", "")
    text = command.get("text", "").strip()

    if not text:
        await say(
            text="Usage: `/forge <workflow description>`\n"
            "Example: `/forge When V75 moves 2%, alert #trading-alerts on Slack`",
            channel=channel_id,
        )
        return

    # Acknowledge the request
    await say(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*ForgeFlow* is processing your request:\n> {text}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": ":hourglass_flowing_sand: Starting autonomous pipeline..."},
                ],
            },
        ],
        channel=channel_id,
    )

    # Run pipeline in background
    asyncio.create_task(_run_pipeline_from_slack(text, channel_id, user_id))


async def _run_pipeline_from_slack(request: str, channel_id: str, user_id: str):
    """Run the ForgeFlow pipeline triggered from Slack."""
    from backend.graph import run_forgeflow_pipeline
    from backend.slack.notifications import send_slack_message
    import uuid

    workflow_id = str(uuid.uuid4())[:8]

    async def slack_event_callback(event: dict):
        """Stream pipeline events to the Slack channel."""
        event_type = event.get("event_type", "")
        message = event.get("message", "")

        # Map event types to emoji indicators
        emoji_map = {
            "conversation.started": ":speech_balloon:",
            "conversation.analyzed": ":brain:",
            "discovery.started": ":mag:",
            "api.discovered": ":white_check_mark:",
            "discovery.complete": ":telescope:",
            "planning.started": ":hammer_and_wrench:",
            "dag.planned": ":deciduous_tree:",
            "codegen.started": ":computer:",
            "code.generated": ":page_facing_up:",
            "security.started": ":shield:",
            "security.complete": ":lock:",
            "execution.started": ":rocket:",
            "execution.success": ":tada:",
            "execution.failed": ":x:",
            "debug.started": ":wrench:",
            "debug.diagnosed": ":stethoscope:",
            "workflow.ready": ":white_check_mark:",
            "workflow.deployed": ":rocket:",
        }

        emoji = emoji_map.get(event_type, ":gear:")

        # Only send key events to avoid spam
        key_events = {
            "conversation.analyzed", "api.discovered", "discovery.complete",
            "dag.planned", "code.generated", "security.complete",
            "execution.started", "execution.success", "execution.failed",
            "debug.started", "debug.diagnosed", "workflow.deployed",
        }

        if event_type in key_events:
            await send_slack_message(channel_id, f"{emoji} {message}")

    try:
        result = await run_forgeflow_pipeline(
            user_request=request,
            workflow_id=workflow_id,
            slack_channel=channel_id,
            event_callback=slack_event_callback,
        )

        # Send final summary
        success = result.get("deployed", False)
        code = result.get("generated_code", "")
        debug_count = len(result.get("debug_history", []))

        if success:
            summary_blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "ForgeFlow: Workflow Deployed!"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Workflow ID:* `{workflow_id}`\n"
                            f"*Status:* Deployed :white_check_mark:\n"
                            f"*Debug Fixes:* {debug_count}\n"
                            f"*Code Length:* {len(code.splitlines())} lines"
                        ),
                    },
                },
            ]

            if code:
                code_preview = code[:2000]
                summary_blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Generated Code:*\n```{code_preview}```",
                    },
                })

            await send_slack_blocks(channel_id, summary_blocks)
        else:
            await send_slack_message(
                channel_id,
                f":warning: Workflow `{workflow_id}` completed with issues. "
                f"Review needed. ({debug_count} debug attempts)"
            )

    except Exception as e:
        logger.error(f"Pipeline failed from Slack: {e}")
        await send_slack_message(
            channel_id,
            f":x: ForgeFlow pipeline error: {str(e)[:200]}"
        )


# ── Slash Command: /forge-status ──────────────────────────────

@slack_app.command("/forge-status")
async def handle_status_command(ack, command, say):
    """Handle /forge-status command."""
    await ack()
    await say(
        text=":clipboard: *ForgeFlow Status*\nNo active workflows. Use `/forge <description>` to create one.",
        channel=command.get("channel_id", ""),
    )


# ── Direct Message Handler ───────────────────────────────────

@slack_app.event("message")
async def handle_message(event, say):
    """Handle direct messages and channel messages to the bot."""
    channel_type = event.get("channel_type", "")
    text = event.get("text", "").strip()
    user = event.get("user", "")
    subtype = event.get("subtype", "")

    print(f"[Slack Event] message received — channel_type={channel_type}, user={user}, text={text[:50]}")

    # Ignore bot's own messages and message edits/deletes
    if event.get("bot_id") or subtype in ("bot_message", "message_changed", "message_deleted"):
        return

    if not text:
        return

    # Respond to DMs
    if channel_type == "im":
        # Check if it's a workflow request
        workflow_keywords = ["when", "create", "build", "automate", "workflow", "send", "alert", "monitor", "every", "if", "trigger"]
        if any(kw in text.lower() for kw in workflow_keywords):
            await say(
                text=f":rocket: *ForgeFlow* is processing your request:\n> {text}\n\n:hourglass_flowing_sand: Starting autonomous pipeline..."
            )
            asyncio.create_task(
                _run_pipeline_from_slack(text, event.get("channel", ""), user)
            )
        else:
            await say(
                text=f":wave: Hi <@{user}>! I'm *ForgeFlow* — an AI-powered workflow generator.\n\n"
                f"*What I can do:*\n"
                f"• Discover APIs automatically (Deriv, Slack, Sheets, Jira, Gmail)\n"
                f"• Generate executable Python workflows\n"
                f"• Self-debug if anything fails\n"
                f"• Deploy as a ready-to-run project\n\n"
                f"*Try it:* Just describe what you want!\n"
                f"_Example: When V75 moves 2% in 5 minutes, send a Slack alert to #trading-alerts, log to Google Sheets, and create a Jira ticket_"
            )


# ── Channel @mention Handler ─────────────────────────────────

@slack_app.event("app_mention")
async def handle_app_mention(event, say):
    """Handle @ForgeFlow mentions in channels."""
    import re

    text = event.get("text", "").strip()
    user = event.get("user", "")
    channel = event.get("channel", "")

    # Strip the bot mention from the text (e.g. "<@U0AEFM0AZTJ> hello" → "hello")
    clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    print(f"[Slack Event] app_mention — channel={channel}, user={user}, text={clean_text[:50]}")

    if not clean_text:
        await say(
            text=f":wave: Hey <@{user}>! I'm *ForgeFlow*.\n\n"
            f"Mention me with a workflow description and I'll build it!\n"
            f"_Example: @ForgeFlow When V75 moves 2%, alert Slack and log to Sheets_\n\n"
            f"Or use `/forge <description>` directly."
        )
        return

    # Check if it's a workflow request
    workflow_keywords = ["when", "create", "build", "automate", "workflow", "send", "alert", "monitor", "every", "if", "trigger"]
    if any(kw in clean_text.lower() for kw in workflow_keywords):
        await say(
            text=f":rocket: *ForgeFlow* is processing your request:\n> {clean_text}\n\n:hourglass_flowing_sand: Starting autonomous pipeline..."
        )
        asyncio.create_task(
            _run_pipeline_from_slack(clean_text, channel, user)
        )
    else:
        await say(
            text=f":wave: Hi <@{user}>! I'm *ForgeFlow* — an AI-powered workflow generator.\n\n"
            f"*Try mentioning me with a workflow:*\n"
            f"_@ForgeFlow When V75 moves 2% in 5 minutes, send a Slack alert to #trading-alerts_\n\n"
            f"Or use `/forge <description>` for the slash command."
        )


# ── App Home Tab ──────────────────────────────────────────────

@slack_app.event("app_home_opened")
async def handle_app_home(event, client: AsyncWebClient):
    """Show app home tab with ForgeFlow info."""
    await client.views_publish(
        user_id=event["user"],
        view={
            "type": "home",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "ForgeFlow"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*AI-Powered Business Workflow Generator*\n\n"
                            "Describe your workflow in plain English, and ForgeFlow will:\n"
                            "1. Discover the right APIs automatically\n"
                            "2. Generate executable Python code\n"
                            "3. Self-debug if anything fails\n"
                            "4. Deploy with zero human intervention\n\n"
                            "Use `/forge <description>` in any channel to get started."
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*Example:*\n"
                            "`/forge When the Volatility 75 Index moves more than 2% in 5 minutes, "
                            "send a Slack alert to #trading-alerts, log to Google Sheets, "
                            "and create a Jira ticket for the risk team`"
                        ),
                    },
                },
            ],
        },
    )


# ── Helper: Send Message ─────────────────────────────────────

async def send_slack_blocks(channel: str, blocks: list[dict]):
    """Send rich blocks to a Slack channel."""
    client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    await client.chat_postMessage(channel=channel, blocks=blocks, text="ForgeFlow Update")


# ── Start Bot ─────────────────────────────────────────────────

async def start_slack_bot():
    """Start the Slack bot in Socket Mode (no public URL needed)."""
    if not settings.SLACK_APP_TOKEN:
        logger.warning("SLACK_APP_TOKEN not set, Slack bot disabled")
        return

    handler = AsyncSocketModeHandler(slack_app, settings.SLACK_APP_TOKEN)
    logger.info("Starting ForgeFlow Slack bot (Socket Mode)...")
    await handler.start_async()
