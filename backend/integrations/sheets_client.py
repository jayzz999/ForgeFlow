"""ForgeFlow Google Sheets Integration — Production-quality Sheets API client.

Provides real, working Google Sheets API calls for reading, writing,
appending data, and creating spreadsheets. Used by generated workflows.

API Docs: https://developers.google.com/sheets/api/reference/rest
Auth: OAuth2 Bearer Token via GOOGLE_SHEETS_ACCESS_TOKEN env var
"""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("forgeflow.integrations.sheets")

BASE_URL = "https://sheets.googleapis.com/v4"


class GoogleSheetsClient:
    """Production Google Sheets API client with retry and error handling."""

    def __init__(
        self,
        access_token: str | None = None,
        spreadsheet_id: str | None = None,
    ):
        self.access_token = access_token or os.getenv("GOOGLE_SHEETS_ACCESS_TOKEN", "")
        self.default_spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SHEET_ID", "")

        if not self.access_token:
            logger.warning("[Sheets] No GOOGLE_SHEETS_ACCESS_TOKEN configured")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, url: str, json_data: dict | None = None,
        params: dict | None = None, retries: int = 3
    ) -> dict:
        """Make an API request with retry logic."""
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
                logger.warning(f"[Sheets] {last_error} (attempt {attempt + 1}/{retries})")
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if e.response.status_code in (400, 401, 403, 404):
                    return {"ok": False, "error": last_error}
            except httpx.RequestError as e:
                last_error = f"Request failed: {str(e)}"
                logger.warning(f"[Sheets] {last_error} (attempt {attempt + 1}/{retries})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Sheets] Unexpected error: {last_error}")

            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

        return {"ok": False, "error": last_error or "max_retries_exceeded"}

    # ── Append Rows ──────────────────────────────────────────────

    async def append_row(
        self, values: list[list], sheet_range: str = "Sheet1!A:Z",
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Append rows to a spreadsheet.

        Args:
            values: 2D array of values, e.g., [["Name", "Email", "Start Date"]]
            sheet_range: A1 notation range (e.g., "Sheet1!A:Z", "Employees!A1")
            spreadsheet_id: Spreadsheet ID (uses default if not provided)
            value_input_option: How to interpret values (USER_ENTERED or RAW)

        Returns:
            {"ok": True, "updated_range": "Sheet1!A5:C5", "updated_rows": 1}
        """
        sid = spreadsheet_id or self.default_spreadsheet_id
        if not sid:
            return {"ok": False, "error": "No spreadsheet ID provided"}

        url = f"{BASE_URL}/spreadsheets/{sid}/values/{sheet_range}:append"
        result = await self._request(
            "POST", url,
            json_data={"values": values},
            params={
                "valueInputOption": value_input_option,
                "insertDataOption": "INSERT_ROWS",
            },
        )
        if result.get("ok"):
            updates = result.get("updates", {})
            logger.info(f"[Sheets] Appended {updates.get('updatedRows', 0)} row(s)")
            return {
                "ok": True,
                "updated_range": updates.get("updatedRange", ""),
                "updated_rows": updates.get("updatedRows", 0),
                "updated_cells": updates.get("updatedCells", 0),
            }
        return result

    async def log_event(
        self, event_name: str, details: str, status: str = "OK",
        spreadsheet_id: str | None = None, sheet_name: str = "Log"
    ) -> dict:
        """Log a workflow event to a tracking spreadsheet.

        Convenience method for workflow tracking. Automatically adds timestamp.

        Args:
            event_name: Event name (e.g., "Onboarding Started", "Email Sent")
            details: Event details
            status: Status string (OK, ERROR, PENDING)
            spreadsheet_id: Spreadsheet ID (optional)
            sheet_name: Sheet/tab name for logging
        """
        import datetime
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        values = [[timestamp, event_name, details, status]]
        return await self.append_row(
            values, f"{sheet_name}!A:D", spreadsheet_id
        )

    # ── Read Data ────────────────────────────────────────────────

    async def read_range(
        self, sheet_range: str = "Sheet1!A1:Z1000",
        spreadsheet_id: str | None = None,
    ) -> dict:
        """Read values from a spreadsheet range.

        Args:
            sheet_range: A1 notation range (e.g., "Sheet1!A1:C10")
            spreadsheet_id: Spreadsheet ID

        Returns:
            {"ok": True, "values": [[...], [...]], "total_rows": 10}
        """
        sid = spreadsheet_id or self.default_spreadsheet_id
        if not sid:
            return {"ok": False, "error": "No spreadsheet ID provided"}

        url = f"{BASE_URL}/spreadsheets/{sid}/values/{sheet_range}"
        result = await self._request("GET", url)
        if result.get("ok"):
            values = result.get("values", [])
            return {
                "ok": True,
                "values": values,
                "total_rows": len(values),
                "range": result.get("range", sheet_range),
            }
        return result

    # ── Update Data ──────────────────────────────────────────────

    async def update_range(
        self, values: list[list], sheet_range: str = "Sheet1!A1",
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Update values in a spreadsheet range.

        Args:
            values: 2D array of values
            sheet_range: A1 notation range (e.g., "Sheet1!A1:C3")
            spreadsheet_id: Spreadsheet ID
            value_input_option: How to interpret values

        Returns:
            {"ok": True, "updated_range": "...", "updated_cells": 6}
        """
        sid = spreadsheet_id or self.default_spreadsheet_id
        if not sid:
            return {"ok": False, "error": "No spreadsheet ID provided"}

        url = f"{BASE_URL}/spreadsheets/{sid}/values/{sheet_range}"
        result = await self._request(
            "PUT", url,
            json_data={"values": values},
            params={"valueInputOption": value_input_option},
        )
        if result.get("ok"):
            logger.info(f"[Sheets] Updated {result.get('updatedCells', 0)} cells")
            return {
                "ok": True,
                "updated_range": result.get("updatedRange", ""),
                "updated_rows": result.get("updatedRows", 0),
                "updated_cells": result.get("updatedCells", 0),
            }
        return result

    # ── Create Spreadsheet ───────────────────────────────────────

    async def create_spreadsheet(
        self, title: str, sheet_names: list[str] | None = None
    ) -> dict:
        """Create a new Google Spreadsheet.

        Args:
            title: Spreadsheet title
            sheet_names: Optional list of sheet/tab names to create

        Returns:
            {"ok": True, "spreadsheet_id": "...", "spreadsheet_url": "...", "title": "..."}
        """
        sheets_config = [
            {"properties": {"title": name}}
            for name in (sheet_names or ["Sheet1"])
        ]

        url = f"{BASE_URL}/spreadsheets"
        result = await self._request("POST", url, {
            "properties": {"title": title},
            "sheets": sheets_config,
        })
        if result.get("ok"):
            sid = result.get("spreadsheetId", "")
            logger.info(f"[Sheets] Spreadsheet created: {title} ({sid})")
            return {
                "ok": True,
                "spreadsheet_id": sid,
                "spreadsheet_url": result.get("spreadsheetUrl", ""),
                "title": title,
            }
        return result
