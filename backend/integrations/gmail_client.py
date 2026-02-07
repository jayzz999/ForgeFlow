"""ForgeFlow Gmail Integration — Production-quality Gmail API client.

Provides real, working Gmail API calls for sending and reading emails.
Used by generated workflows.

API Docs: https://developers.google.com/gmail/api/reference/rest
Auth: OAuth2 Bearer Token via GMAIL_ACCESS_TOKEN env var
"""

import asyncio
import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

logger = logging.getLogger("forgeflow.integrations.gmail")

BASE_URL = "https://gmail.googleapis.com/gmail/v1"


class GmailClient:
    """Production Gmail API client with retry and error handling."""

    def __init__(
        self,
        access_token: str | None = None,
        sender_email: str | None = None,
    ):
        self.access_token = access_token or os.getenv("GMAIL_ACCESS_TOKEN", "")
        self.sender_email = sender_email or os.getenv("GMAIL_SENDER_EMAIL", "")

        if not self.access_token:
            logger.warning("[Gmail] No GMAIL_ACCESS_TOKEN configured")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, json_data: dict | None = None,
        params: dict | None = None, retries: int = 3
    ) -> dict:
        """Make an API request with retry logic."""
        url = f"{BASE_URL}/{path.lstrip('/')}"
        last_error = None

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.request(
                        method, url,
                        headers=self._headers(),
                        json=json_data,
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return {"ok": True, **data}

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
                logger.warning(f"[Gmail] {last_error} (attempt {attempt + 1}/{retries})")
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if e.response.status_code in (400, 401, 403, 404):
                    return {"ok": False, "error": last_error}
            except httpx.RequestError as e:
                last_error = f"Request failed: {str(e)}"
                logger.warning(f"[Gmail] {last_error} (attempt {attempt + 1}/{retries})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Gmail] Unexpected error: {last_error}")

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

        return {"ok": False, "error": last_error or "max_retries_exceeded"}

    # ── Send Email ───────────────────────────────────────────────

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict:
        """Send an email via Gmail API.

        Args:
            to: Recipient email address (or comma-separated list)
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML body (sends multipart if provided)
            cc: CC recipients (comma-separated)
            bcc: BCC recipients (comma-separated)

        Returns:
            {"ok": True, "message_id": "...", "thread_id": "..."}
        """
        if html_body:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg = MIMEText(body, "plain")

        msg["To"] = to
        msg["Subject"] = subject
        if self.sender_email:
            msg["From"] = self.sender_email
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        # Encode to base64url format required by Gmail API
        raw = base64.urlsafe_b64encode(msg.as_string().encode()).decode()

        result = await self._request(
            "POST", "users/me/messages/send",
            {"raw": raw},
        )
        if result.get("ok"):
            msg_id = result.get("id", "")
            logger.info(f"[Gmail] Email sent to {to} (id={msg_id})")
            return {
                "ok": True,
                "message_id": msg_id,
                "thread_id": result.get("threadId", ""),
            }
        return result

    async def send_welcome_email(
        self, to: str, employee_name: str, start_date: str = "",
        manager_name: str = "", extra_info: str = ""
    ) -> dict:
        """Send a formatted welcome email for employee onboarding.

        Args:
            to: New employee email
            employee_name: Employee's full name
            start_date: Start date string
            manager_name: Manager's name
            extra_info: Additional onboarding info
        """
        subject = f"Welcome to the team, {employee_name}!"

        body = f"""Hi {employee_name},

Welcome to the team! We're excited to have you join us{f' starting {start_date}' if start_date else ''}.

{f'Your manager, {manager_name}, will be reaching out to schedule your first day.' if manager_name else 'Your manager will be reaching out soon.'}

Here are some things to expect:
- You'll receive IT setup instructions shortly
- HR will share your onboarding documents
- A team introduction will be scheduled for your first week

{extra_info if extra_info else ''}

If you have any questions before your start date, feel free to reply to this email.

Best regards,
The Team
"""
        html_body = f"""<html><body>
<h2>Welcome to the team, {employee_name}! 🎉</h2>
<p>We're excited to have you join us{f' starting <strong>{start_date}</strong>' if start_date else ''}.</p>
<p>{f'Your manager, <strong>{manager_name}</strong>, will be reaching out to schedule your first day.' if manager_name else 'Your manager will be reaching out soon.'}</p>
<h3>Here are some things to expect:</h3>
<ul>
<li>📧 You'll receive IT setup instructions shortly</li>
<li>📋 HR will share your onboarding documents</li>
<li>👋 A team introduction will be scheduled for your first week</li>
</ul>
{f'<p>{extra_info}</p>' if extra_info else ''}
<p>If you have any questions before your start date, feel free to reply to this email.</p>
<p>Best regards,<br>The Team</p>
</body></html>"""

        return await self.send_email(to, subject, body, html_body)

    # ── Read Email ───────────────────────────────────────────────

    async def list_messages(
        self, query: str = "", max_results: int = 10, label_ids: list[str] | None = None
    ) -> dict:
        """List messages matching a query.

        Args:
            query: Gmail search query (e.g., "from:boss@company.com is:unread")
            max_results: Maximum number of messages to return
            label_ids: Filter by label IDs (e.g., ["INBOX", "UNREAD"])

        Returns:
            {"ok": True, "messages": [{"id": "...", "threadId": "..."}], "total": 10}
        """
        params = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = ",".join(label_ids)

        result = await self._request("GET", "users/me/messages", params=params)
        if result.get("ok"):
            return {
                "ok": True,
                "messages": result.get("messages", []),
                "total": result.get("resultSizeEstimate", 0),
            }
        return result

    async def get_message(self, message_id: str, format: str = "metadata") -> dict:
        """Get a specific message by ID.

        Args:
            message_id: Message ID
            format: Response format (full, metadata, minimal, raw)

        Returns:
            {"ok": True, "id": "...", "subject": "...", "from": "...", "snippet": "..."}
        """
        result = await self._request(
            "GET", f"users/me/messages/{message_id}",
            params={"format": format},
        )
        if result.get("ok"):
            headers = {
                h["name"].lower(): h["value"]
                for h in result.get("payload", {}).get("headers", [])
                if h.get("name", "").lower() in ("subject", "from", "to", "date")
            }
            return {
                "ok": True,
                "id": result.get("id"),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "snippet": result.get("snippet", ""),
            }
        return result

    async def list_labels(self) -> dict:
        """List all Gmail labels.

        Returns:
            {"ok": True, "labels": [{"id": "...", "name": "...", "type": "..."}]}
        """
        result = await self._request("GET", "users/me/labels")
        if result.get("ok"):
            labels = [
                {
                    "id": l.get("id"),
                    "name": l.get("name"),
                    "type": l.get("type"),
                }
                for l in result.get("labels", [])
            ]
            return {"ok": True, "labels": labels}
        return result
