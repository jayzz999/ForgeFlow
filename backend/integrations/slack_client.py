"""ForgeFlow Slack Integration — Production-quality Slack API client.

Provides real, working Slack API calls with retry logic, error handling,
and structured responses. Used by generated workflows.

API Docs: https://api.slack.com/methods
Auth: Bot Token (xoxb-*) via SLACK_BOT_TOKEN env var
"""

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("forgeflow.integrations.slack")

BASE_URL = "https://slack.com/api"


class SlackClient:
    """Production Slack API client with retry and error handling."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("SLACK_BOT_TOKEN", "")
        if not self.token:
            logger.warning("[Slack] No SLACK_BOT_TOKEN configured")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def _request(
        self, method: str, endpoint: str, json_data: dict | None = None,
        retries: int = 3
    ) -> dict:
        """Make an API request with retry logic."""
        url = f"{BASE_URL}/{endpoint}"
        last_error = None

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    if method == "GET":
                        resp = await client.get(url, headers=self._headers(), params=json_data)
                    else:
                        resp = await client.post(url, headers=self._headers(), json=json_data)

                    resp.raise_for_status()
                    data = resp.json()

                    if not data.get("ok"):
                        error = data.get("error", "unknown_error")
                        logger.error(f"[Slack] API error: {error} for {endpoint}")
                        if error in ("ratelimited",):
                            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                            await asyncio.sleep(retry_after)
                            continue
                        return {"ok": False, "error": error}

                    return data

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                logger.warning(f"[Slack] {last_error} (attempt {attempt + 1}/{retries})")
            except httpx.RequestError as e:
                last_error = f"Request failed: {str(e)}"
                logger.warning(f"[Slack] {last_error} (attempt {attempt + 1}/{retries})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Slack] Unexpected error: {last_error}")

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

        return {"ok": False, "error": last_error or "max_retries_exceeded"}

    # ── Messaging ────────────────────────────────────────────────

    async def send_message(
        self, channel: str, text: str, blocks: list | None = None,
        thread_ts: str | None = None
    ) -> dict:
        """Send a message to a Slack channel or DM.

        Args:
            channel: Channel name (#general) or ID (C1234567890)
            text: Message text (supports markdown)
            blocks: Optional Block Kit blocks for rich formatting
            thread_ts: Optional thread timestamp for replies

        Returns:
            {"ok": True, "message_ts": "1234567890.123456", "channel": "C1234567890"}
        """
        payload = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        result = await self._request("POST", "chat.postMessage", payload)
        if result.get("ok"):
            logger.info(f"[Slack] Message sent to {channel}")
            return {
                "ok": True,
                "message_ts": result.get("ts"),
                "channel": result.get("channel"),
            }
        return result

    async def send_rich_message(
        self, channel: str, title: str, body: str, color: str = "#36a64f",
        fields: list[dict] | None = None
    ) -> dict:
        """Send a rich formatted message with attachment.

        Args:
            channel: Channel name or ID
            title: Attachment title
            body: Attachment body text
            color: Sidebar color (hex)
            fields: Optional fields [{"title": "...", "value": "...", "short": True}]
        """
        attachment = {
            "color": color,
            "title": title,
            "text": body,
            "fields": fields or [],
            "footer": "ForgeFlow",
        }
        payload = {"channel": channel, "attachments": [attachment], "text": title}
        return await self._request("POST", "chat.postMessage", payload)

    # ── Channels ─────────────────────────────────────────────────

    async def create_channel(self, name: str, is_private: bool = False) -> dict:
        """Create a new Slack channel.

        Args:
            name: Channel name (lowercase, no spaces)
            is_private: Whether to create a private channel

        Returns:
            {"ok": True, "channel_id": "C1234567890", "channel_name": "my-channel"}
        """
        result = await self._request("POST", "conversations.create", {
            "name": name.lower().replace(" ", "-"),
            "is_private": is_private,
        })
        if result.get("ok"):
            ch = result.get("channel", {})
            logger.info(f"[Slack] Channel created: {ch.get('name')}")
            return {
                "ok": True,
                "channel_id": ch.get("id"),
                "channel_name": ch.get("name"),
            }
        return result

    async def invite_to_channel(self, channel_id: str, user_ids: list[str]) -> dict:
        """Invite users to a channel.

        Args:
            channel_id: Channel ID (C1234567890)
            user_ids: List of user IDs to invite
        """
        result = await self._request("POST", "conversations.invite", {
            "channel": channel_id,
            "users": ",".join(user_ids),
        })
        if result.get("ok"):
            logger.info(f"[Slack] Invited {len(user_ids)} users to {channel_id}")
        return result

    async def list_channels(self, limit: int = 100) -> dict:
        """List all accessible channels.

        Returns:
            {"ok": True, "channels": [{"id": "...", "name": "...", "num_members": ...}]}
        """
        result = await self._request("GET", "conversations.list", {
            "limit": limit,
            "types": "public_channel,private_channel",
        })
        if result.get("ok"):
            channels = [
                {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "num_members": ch.get("num_members", 0),
                    "is_private": ch.get("is_private", False),
                }
                for ch in result.get("channels", [])
            ]
            return {"ok": True, "channels": channels}
        return result

    # ── Users ────────────────────────────────────────────────────

    async def lookup_user_by_email(self, email: str) -> dict:
        """Find a Slack user by email address.

        Args:
            email: User's email address

        Returns:
            {"ok": True, "user_id": "U1234567890", "display_name": "John Doe"}
        """
        result = await self._request("GET", "users.lookupByEmail", {"email": email})
        if result.get("ok"):
            user = result.get("user", {})
            profile = user.get("profile", {})
            return {
                "ok": True,
                "user_id": user.get("id"),
                "display_name": profile.get("display_name") or profile.get("real_name", ""),
                "email": profile.get("email", email),
            }
        return result

    async def list_users(self, limit: int = 100) -> dict:
        """List workspace users.

        Returns:
            {"ok": True, "users": [{"id": "...", "name": "...", "email": "..."}]}
        """
        result = await self._request("GET", "users.list", {"limit": limit})
        if result.get("ok"):
            users = [
                {
                    "id": m.get("id"),
                    "name": m.get("profile", {}).get("real_name", m.get("name", "")),
                    "email": m.get("profile", {}).get("email", ""),
                }
                for m in result.get("members", [])
                if not m.get("is_bot") and not m.get("deleted")
            ]
            return {"ok": True, "users": users}
        return result

    # ── Reactions & Files ────────────────────────────────────────

    async def add_reaction(self, channel: str, timestamp: str, emoji: str) -> dict:
        """Add an emoji reaction to a message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            emoji: Emoji name without colons (e.g., "thumbsup")
        """
        return await self._request("POST", "reactions.add", {
            "channel": channel,
            "timestamp": timestamp,
            "name": emoji.strip(":"),
        })

    async def upload_file(
        self, channels: str, content: str, filename: str = "file.txt",
        title: str | None = None
    ) -> dict:
        """Upload a file to a channel.

        Args:
            channels: Comma-separated channel IDs
            content: File content as string
            filename: Name for the file
            title: Optional title for the file
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BASE_URL}/files.upload",
                headers={"Authorization": f"Bearer {self.token}"},
                data={
                    "channels": channels,
                    "content": content,
                    "filename": filename,
                    "title": title or filename,
                },
            )
            data = resp.json()
            if data.get("ok"):
                logger.info(f"[Slack] File uploaded: {filename}")
            return data
