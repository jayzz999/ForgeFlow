"""Additional Slack event handlers and utilities."""

from backend.slack.bot import slack_app


@slack_app.event("app_mention")
async def handle_mention(event, say):
    """Handle @ForgeFlow mentions in channels."""
    text = event.get("text", "")
    user = event.get("user", "")

    # Remove the bot mention from the text
    # Format is typically "<@BOT_ID> message"
    import re
    clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    if not clean_text:
        await say(
            text=f"<@{user}> Hi! Use `/forge <description>` to create a workflow, "
            "or mention me with a workflow description."
        )
        return

    await say(text=f":hourglass_flowing_sand: <@{user}> Processing your request...")

    import asyncio
    from backend.slack.bot import _run_pipeline_from_slack
    asyncio.create_task(
        _run_pipeline_from_slack(clean_text, event.get("channel", ""), user)
    )


@slack_app.action("approve_workflow")
async def handle_approve(ack, action, say):
    """Handle workflow approval button click."""
    await ack()
    await say(text=":white_check_mark: Workflow approved and deploying...")


@slack_app.action("reject_workflow")
async def handle_reject(ack, action, say):
    """Handle workflow rejection button click."""
    await ack()
    await say(text=":no_entry_sign: Workflow rejected. Use `/forge` to try again.")
