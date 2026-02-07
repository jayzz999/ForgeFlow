"""Tool executor — runs tool calls from the LLM agent.

Each tool function takes the tool arguments dict and an optional project
directory, executes the action, and returns a result string that gets
fed back to the LLM.
"""

import asyncio
import json
import logging
import os
import re

import httpx

logger = logging.getLogger("forgeflow.tools")

# Commands that are never allowed
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){", "fork",
    "shutdown", "reboot", "poweroff", "halt", "init 0", "init 6",
    "chmod -R 777 /", "chown -R", "wget -O- | sh", "curl | sh",
    "sudo", "su -", "passwd", "userdel", "groupdel",
}

# Max content sizes
MAX_PAGE_CHARS = 12000
MAX_RESPONSE_CHARS = 8000
MAX_FILE_CHARS = 50000


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    project_dir: str = "/tmp/forgeflow_project",
) -> str:
    """Execute a tool call and return the result as a string."""
    try:
        if tool_name == "fetch_web_page":
            return await _fetch_web_page(tool_args)
        elif tool_name == "execute_shell":
            return await _execute_shell(tool_args, project_dir)
        elif tool_name == "write_file":
            return await _write_file(tool_args, project_dir)
        elif tool_name == "read_file":
            return await _read_file(tool_args, project_dir)
        elif tool_name == "test_api_endpoint":
            return await _test_api_endpoint(tool_args)
        else:
            return f"Error: Unknown tool '{tool_name}'"
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}")
        return f"Error executing {tool_name}: {str(e)}"


# ── Tool Implementations ─────────────────────────────────────

async def _fetch_web_page(args: dict) -> str:
    """Fetch a web page and return its text content."""
    url = args.get("url", "")
    extract_code = args.get("extract_code", False)

    if not url:
        return "Error: url is required"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "ForgeFlow-Agent/1.0 (AI workflow generator)",
            })
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code}: {str(e)[:200]}"
    except Exception as e:
        return f"Fetch error: {str(e)[:200]}"

    content = resp.text

    # Try to extract useful text from HTML
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "lxml")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        if extract_code:
            # Extract only code blocks
            code_blocks = []
            for code_tag in soup.find_all(["code", "pre"]):
                text = code_tag.get_text(strip=True)
                if text and len(text) > 10:
                    code_blocks.append(text)
            text = "\n\n---\n\n".join(code_blocks) if code_blocks else soup.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)
    except ImportError:
        # Fallback: basic HTML tag stripping
        text = re.sub(r'<[^>]+>', '', content)

    # Truncate
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + f"\n\n[Truncated — {len(text)} chars total]"

    return text


async def _execute_shell(args: dict, project_dir: str) -> str:
    """Execute a shell command in the project directory."""
    command = args.get("command", "")
    timeout = min(args.get("timeout", 30), 60)

    if not command:
        return "Error: command is required"

    # Check for blocked commands
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return f"Error: Command blocked for safety — '{blocked}' is not allowed"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Error: Command timed out after {timeout}s"

        stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_RESPONSE_CHARS]
        stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_RESPONSE_CHARS]

        result = f"Exit code: {proc.returncode}\n"
        if stdout_str:
            result += f"STDOUT:\n{stdout_str}\n"
        if stderr_str:
            result += f"STDERR:\n{stderr_str}\n"

        return result.strip()

    except Exception as e:
        return f"Error: {str(e)[:200]}"


async def _write_file(args: dict, project_dir: str) -> str:
    """Write a file to the project directory."""
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return "Error: path is required"

    # Security: prevent path traversal
    normalized = os.path.normpath(path)
    if normalized.startswith("..") or os.path.isabs(normalized):
        return "Error: Path must be relative and within the project directory"

    full_path = os.path.join(project_dir, normalized)

    # Create parent directories
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content)

    return f"Written {len(content)} chars to {normalized}"


async def _read_file(args: dict, project_dir: str) -> str:
    """Read a file from the project directory."""
    path = args.get("path", "")

    if not path:
        return "Error: path is required"

    # Security: prevent path traversal
    normalized = os.path.normpath(path)
    if normalized.startswith("..") or os.path.isabs(normalized):
        return "Error: Path must be relative and within the project directory"

    full_path = os.path.join(project_dir, normalized)

    if not os.path.exists(full_path):
        return f"Error: File not found — {normalized}"

    with open(full_path) as f:
        content = f.read()

    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS] + f"\n\n[Truncated — {len(content)} chars total]"

    return content


async def _test_api_endpoint(args: dict) -> str:
    """Make an HTTP request to test an API endpoint."""
    method = args.get("method", "GET").upper()
    url = args.get("url", "")
    headers_str = args.get("headers", "{}")
    body_str = args.get("body", "")

    if not url:
        return "Error: url is required"

    try:
        headers = json.loads(headers_str) if headers_str else {}
    except json.JSONDecodeError:
        headers = {}

    try:
        body = json.loads(body_str) if body_str else None
    except json.JSONDecodeError:
        body = None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body if body else None,
            )

        # Format response
        body_text = resp.text[:MAX_RESPONSE_CHARS]
        result = (
            f"HTTP {resp.status_code} {resp.reason_phrase}\n"
            f"Headers: {dict(list(resp.headers.items())[:10])}\n"
            f"Body:\n{body_text}"
        )
        return result

    except Exception as e:
        return f"Request error: {str(e)[:300]}"
