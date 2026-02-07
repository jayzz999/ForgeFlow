"""ForgeFlow Jira Integration — Production-quality Jira Cloud API client.

Provides real, working Jira API calls for issue management, transitions,
search, and comments. Used by generated workflows.

API Docs: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
Auth: Basic Auth (email:api_token) via JIRA_EMAIL + JIRA_API_TOKEN env vars
"""

import asyncio
import base64
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("forgeflow.integrations.jira")


class JiraClient:
    """Production Jira Cloud API client with retry and error handling."""

    def __init__(
        self,
        domain: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ):
        self.domain = domain or os.getenv("JIRA_DOMAIN", "")
        self.email = email or os.getenv("JIRA_EMAIL", "")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN", "")

        if not self.domain:
            logger.warning("[Jira] No JIRA_DOMAIN configured")
        if not self.api_token:
            logger.warning("[Jira] No JIRA_API_TOKEN configured")

        self.base_url = f"https://{self.domain}.atlassian.net/rest/api/3"

    def _headers(self) -> dict:
        creds = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        return {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self, method: str, path: str, json_data: dict | None = None,
        params: dict | None = None, retries: int = 3
    ) -> dict:
        """Make an API request with retry logic."""
        url = f"{self.base_url}/{path.lstrip('/')}"
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

                    if resp.status_code == 204:
                        return {"ok": True}

                    data = resp.json()
                    return {"ok": True, **data}

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
                logger.warning(f"[Jira] {last_error} (attempt {attempt + 1}/{retries})")
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 2 ** attempt))
                    await asyncio.sleep(retry_after)
                    continue
                if e.response.status_code in (400, 401, 403, 404):
                    return {"ok": False, "error": last_error}
            except httpx.RequestError as e:
                last_error = f"Request failed: {str(e)}"
                logger.warning(f"[Jira] {last_error} (attempt {attempt + 1}/{retries})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Jira] Unexpected error: {last_error}")

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

        return {"ok": False, "error": last_error or "max_retries_exceeded"}

    # ── Issues ───────────────────────────────────────────────────

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str = "",
        priority: str = "Medium",
        assignee_id: str | None = None,
        labels: list[str] | None = None,
        custom_fields: dict | None = None,
    ) -> dict:
        """Create a new Jira issue.

        Args:
            project_key: Project key (e.g., "PROJ", "HR", "ENG")
            summary: Issue title/summary
            issue_type: Issue type (Task, Bug, Story, Epic)
            description: Issue description (supports ADF format)
            priority: Priority level (Highest, High, Medium, Low, Lowest)
            assignee_id: Atlassian account ID to assign to
            labels: List of labels to add
            custom_fields: Additional custom fields

        Returns:
            {"ok": True, "issue_key": "PROJ-123", "issue_id": "10001",
             "issue_url": "https://domain.atlassian.net/browse/PROJ-123"}
        """
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }

        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }

        if assignee_id:
            fields["assignee"] = {"accountId": assignee_id}

        if labels:
            fields["labels"] = labels

        if custom_fields:
            fields.update(custom_fields)

        result = await self._request("POST", "issue", {"fields": fields})
        if result.get("ok"):
            issue_key = result.get("key", "")
            logger.info(f"[Jira] Issue created: {issue_key}")
            return {
                "ok": True,
                "issue_key": issue_key,
                "issue_id": result.get("id", ""),
                "issue_url": f"https://{self.domain}.atlassian.net/browse/{issue_key}",
            }
        return result

    async def get_issue(self, issue_key: str, fields: str = "*all") -> dict:
        """Get issue details by key.

        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            fields: Comma-separated fields or "*all"

        Returns:
            {"ok": True, "key": "PROJ-123", "summary": "...", "status": "...", ...}
        """
        result = await self._request("GET", f"issue/{issue_key}", params={"fields": fields})
        if result.get("ok"):
            f = result.get("fields", {})
            return {
                "ok": True,
                "key": result.get("key", issue_key),
                "summary": f.get("summary", ""),
                "status": f.get("status", {}).get("name", ""),
                "priority": f.get("priority", {}).get("name", ""),
                "assignee": f.get("assignee", {}).get("displayName", "Unassigned") if f.get("assignee") else "Unassigned",
                "issue_type": f.get("issuetype", {}).get("name", ""),
                "created": f.get("created", ""),
                "updated": f.get("updated", ""),
            }
        return result

    async def update_issue(
        self, issue_key: str, summary: str | None = None,
        description: str | None = None, priority: str | None = None,
        labels: list[str] | None = None, custom_fields: dict | None = None,
    ) -> dict:
        """Update an existing issue.

        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            summary: New summary (optional)
            description: New description (optional)
            priority: New priority (optional)
            labels: New labels (optional)
            custom_fields: Additional custom fields (optional)
        """
        fields: dict[str, Any] = {}

        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]}
                ],
            }
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        if custom_fields:
            fields.update(custom_fields)

        result = await self._request("PUT", f"issue/{issue_key}", {"fields": fields})
        if result.get("ok"):
            logger.info(f"[Jira] Issue updated: {issue_key}")
        return result

    async def transition_issue(self, issue_key: str, transition_name: str) -> dict:
        """Transition an issue to a new status.

        Args:
            issue_key: Issue key
            transition_name: Target status name (e.g., "In Progress", "Done")
        """
        # First, get available transitions
        transitions_result = await self._request("GET", f"issue/{issue_key}/transitions")
        if not transitions_result.get("ok"):
            return transitions_result

        transitions = transitions_result.get("transitions", [])
        target = None
        for t in transitions:
            if t.get("name", "").lower() == transition_name.lower():
                target = t
                break

        if not target:
            available = [t.get("name") for t in transitions]
            return {
                "ok": False,
                "error": f"Transition '{transition_name}' not found. Available: {available}",
            }

        result = await self._request(
            "POST", f"issue/{issue_key}/transitions",
            {"transition": {"id": target["id"]}},
        )
        if result.get("ok"):
            logger.info(f"[Jira] Issue {issue_key} transitioned to {transition_name}")
        return result

    async def add_comment(self, issue_key: str, body: str) -> dict:
        """Add a comment to an issue.

        Args:
            issue_key: Issue key
            body: Comment text
        """
        comment_body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": body}]}
                ],
            }
        }
        result = await self._request("POST", f"issue/{issue_key}/comment", comment_body)
        if result.get("ok"):
            logger.info(f"[Jira] Comment added to {issue_key}")
            return {"ok": True, "comment_id": result.get("id", "")}
        return result

    async def assign_issue(self, issue_key: str, account_id: str) -> dict:
        """Assign an issue to a user.

        Args:
            issue_key: Issue key
            account_id: Atlassian account ID
        """
        return await self._request("PUT", f"issue/{issue_key}/assignee", {
            "accountId": account_id,
        })

    async def search_issues(
        self, jql: str, max_results: int = 50,
        fields: list[str] | None = None
    ) -> dict:
        """Search issues using JQL.

        Args:
            jql: JQL query (e.g., 'project = PROJ AND status = "To Do"')
            max_results: Maximum results to return
            fields: Fields to include

        Returns:
            {"ok": True, "total": 10, "issues": [...]}
        """
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields or ["summary", "status", "priority", "assignee", "created"],
        }
        result = await self._request("POST", "search", payload)
        if result.get("ok"):
            issues = [
                {
                    "key": issue.get("key"),
                    "summary": issue.get("fields", {}).get("summary", ""),
                    "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                    "priority": issue.get("fields", {}).get("priority", {}).get("name", ""),
                }
                for issue in result.get("issues", [])
            ]
            return {"ok": True, "total": result.get("total", 0), "issues": issues}
        return result
