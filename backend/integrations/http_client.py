"""ForgeFlow HTTP Integration — Generic REST API client.

Provides a flexible HTTP client for any REST API, webhooks, health checks,
and custom integrations. Used by generated workflows when no specific
service client exists.

Supports: GET, POST, PUT, PATCH, DELETE with retry, auth, and headers.
"""

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("forgeflow.integrations.http")


class HTTPClient:
    """Production generic HTTP client with retry and error handling."""

    def __init__(
        self,
        base_url: str = "",
        default_headers: dict | None = None,
        auth_token: str | None = None,
        auth_type: str = "bearer",
        timeout: float = 30.0,
    ):
        """Initialize HTTP client.

        Args:
            base_url: Base URL for all requests (e.g., "https://api.example.com/v1")
            default_headers: Headers applied to all requests
            auth_token: Authentication token
            auth_type: "bearer", "basic", "api_key", or "custom"
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.auth_token = auth_token
        self.auth_type = auth_type
        self.timeout = timeout

        if auth_token:
            if auth_type == "bearer":
                self.default_headers["Authorization"] = f"Bearer {auth_token}"
            elif auth_type == "basic":
                self.default_headers["Authorization"] = f"Basic {auth_token}"
            elif auth_type == "api_key":
                self.default_headers["X-API-Key"] = auth_token

    def _build_url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if self.base_url else path

    async def _request(
        self, method: str, path: str, json_data: Any = None,
        params: dict | None = None, headers: dict | None = None,
        data: Any = None, retries: int = 3
    ) -> dict:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: URL path or full URL
            json_data: JSON request body
            params: Query parameters
            headers: Additional headers (merged with defaults)
            data: Form data body
            retries: Max retry attempts

        Returns:
            {"ok": True, "status": 200, "data": {...}, "headers": {...}}
        """
        url = self._build_url(path)
        req_headers = {**self.default_headers, **(headers or {})}
        last_error = None

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(
                        method, url,
                        headers=req_headers,
                        json=json_data,
                        params=params,
                        data=data,
                    )

                    response_data = None
                    content_type = resp.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            response_data = resp.json()
                        except Exception:
                            response_data = resp.text
                    else:
                        response_data = resp.text

                    if resp.status_code >= 400:
                        last_error = f"HTTP {resp.status_code}: {str(response_data)[:300]}"
                        if resp.status_code == 429:
                            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                            await asyncio.sleep(retry_after)
                            continue
                        if resp.status_code in (400, 401, 403, 404, 405):
                            return {
                                "ok": False,
                                "status": resp.status_code,
                                "error": last_error,
                                "data": response_data,
                            }
                        logger.warning(f"[HTTP] {last_error} (attempt {attempt + 1})")
                    else:
                        return {
                            "ok": True,
                            "status": resp.status_code,
                            "data": response_data,
                            "headers": dict(resp.headers),
                        }

            except httpx.RequestError as e:
                last_error = f"Request failed: {str(e)}"
                logger.warning(f"[HTTP] {last_error} (attempt {attempt + 1}/{retries})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[HTTP] Unexpected error: {last_error}")

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

        return {"ok": False, "error": last_error or "max_retries_exceeded"}

    # ── Convenience Methods ──────────────────────────────────────

    async def get(self, path: str, params: dict | None = None, **kwargs) -> dict:
        """HTTP GET request."""
        return await self._request("GET", path, params=params, **kwargs)

    async def post(self, path: str, json_data: Any = None, **kwargs) -> dict:
        """HTTP POST request."""
        return await self._request("POST", path, json_data=json_data, **kwargs)

    async def put(self, path: str, json_data: Any = None, **kwargs) -> dict:
        """HTTP PUT request."""
        return await self._request("PUT", path, json_data=json_data, **kwargs)

    async def patch(self, path: str, json_data: Any = None, **kwargs) -> dict:
        """HTTP PATCH request."""
        return await self._request("PATCH", path, json_data=json_data, **kwargs)

    async def delete(self, path: str, **kwargs) -> dict:
        """HTTP DELETE request."""
        return await self._request("DELETE", path, **kwargs)

    # ── Specialized Methods ──────────────────────────────────────

    async def health_check(self, url: str, expected_status: int = 200) -> dict:
        """Check if a URL is accessible and returns expected status.

        Args:
            url: URL to check
            expected_status: Expected HTTP status code

        Returns:
            {"ok": True, "status": 200, "response_time_ms": 150, "healthy": True}
        """
        import time
        start = time.monotonic()

        result = await self._request("GET", url, retries=1)
        elapsed = (time.monotonic() - start) * 1000

        is_healthy = result.get("status") == expected_status
        return {
            "ok": True,
            "status": result.get("status", 0),
            "response_time_ms": round(elapsed, 2),
            "healthy": is_healthy,
            "url": url,
        }

    async def webhook(
        self, url: str, payload: dict, secret: str | None = None
    ) -> dict:
        """Send a webhook POST request.

        Args:
            url: Webhook URL
            payload: JSON payload
            secret: Optional webhook secret for HMAC signing

        Returns:
            {"ok": True, "status": 200, "data": ...}
        """
        headers = {"Content-Type": "application/json"}
        if secret:
            import hashlib
            import hmac
            import json as json_mod
            body = json_mod.dumps(payload).encode()
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={sig}"

        return await self._request("POST", url, json_data=payload, headers=headers)

    async def send_to_webhook(
        self, webhook_url: str, event_type: str, data: dict
    ) -> dict:
        """Send a structured event to a webhook endpoint.

        Args:
            webhook_url: Target webhook URL
            event_type: Event type identifier
            data: Event data payload
        """
        import datetime
        payload = {
            "event_type": event_type,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "data": data,
            "source": "forgeflow",
        }
        return await self.webhook(webhook_url, payload)

    async def download_file(self, url: str) -> dict:
        """Download a file from a URL.

        Args:
            url: File URL

        Returns:
            {"ok": True, "content": bytes, "content_type": "...", "size": 1234}
        """
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return {
                    "ok": True,
                    "content": resp.content,
                    "content_type": resp.headers.get("content-type", ""),
                    "size": len(resp.content),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}
