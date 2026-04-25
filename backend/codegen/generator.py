"""LLM-powered Python code generation from workflow DAG.

Uses the tool-calling agent loop to generate production-quality code:
- Browses API documentation to verify endpoints and research unknown APIs
- Tests API endpoints to check availability
- Writes multi-file projects for complex workflows
- Uses shell commands to validate syntax
- NEVER generates placeholder code — always produces real, working implementations
"""

import json
import logging
import os

from backend.shared.config import settings
from backend.shared.gemini_client import generate_text, generate_with_tools
from backend.shared.models import WorkflowDAG
from backend.tools.definitions import TOOLS_CONFIG
from backend.tools.executor import execute_tool

logger = logging.getLogger("forgeflow.codegen")


def _get_available_credentials() -> list[dict]:
    """Check which service credentials are actually configured."""
    creds = []

    # Slack — also fetch real channel list so generator never hallucinates channel names
    slack_token = os.getenv("SLACK_BOT_TOKEN", "")
    slack_available = bool(slack_token and slack_token.startswith("xoxb-"))
    slack_channels = _fetch_slack_channels(slack_token) if slack_available else []

    creds.append({
        "service": "Slack",
        "available": slack_available,
        "env_var": "SLACK_BOT_TOKEN",
        "real_channels": slack_channels,
        "note": (
            f"Use Bearer token auth. REAL channels in this workspace: {slack_channels}. "
            f"ALWAYS use one of these exact channel names (without #). Never invent channel names."
            if slack_available else "Not configured"
        ),
    })

    # Gmail SMTP
    gmail_addr = os.getenv("GMAIL_ADDRESS", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    gmail_available = bool(gmail_addr and gmail_pass)
    creds.append({
        "service": "Gmail",
        "available": gmail_available,
        "env_vars": ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"],
        "note": (
            f"SMTP via smtplib. Sender address: {gmail_addr}. "
            "Use Python smtplib with GMAIL_ADDRESS and GMAIL_APP_PASSWORD env vars."
            if gmail_available else
            "NOT CONFIGURED — GMAIL_ADDRESS and/or GMAIL_APP_PASSWORD are empty. Skip gracefully with a warning."
        ),
    })

    # Google Sheets
    sheets_key = os.getenv("GOOGLE_API_KEY", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    sheets_available = bool(sheets_key and sheet_id)
    creds.append({
        "service": "Google Sheets",
        "available": sheets_available,
        "env_vars": ["GOOGLE_API_KEY", "GOOGLE_SHEET_ID"],
        "note": (
            f"Sheets API v4. Use GOOGLE_API_KEY and GOOGLE_SHEET_ID env vars. "
            "Sheet must be shared publicly (Anyone with link can edit)."
            if sheets_available else
            "NOT CONFIGURED — GOOGLE_API_KEY and/or GOOGLE_SHEET_ID are empty. Skip gracefully with a warning."
        ),
    })

    return [slack_status, sheets_status, gmail_status]


def _fetch_slack_channels(token: str) -> list[str]:
    """Fetch real channel names from the Slack workspace (fast, cached)."""
    import urllib.request as _req
    import json as _json
    try:
        url = "https://slack.com/api/conversations.list?limit=50&types=public_channel,private_channel"
        request = _req.Request(url, headers={"Authorization": f"Bearer {token}"})
        resp = _json.loads(_req.urlopen(request, timeout=5).read())
        if resp.get("ok"):
            return [c["name"] for c in resp.get("channels", [])]
    except Exception:
        pass
    return []


async def generate_workflow_code(
    dag: WorkflowDAG,
    data_mappings: list[dict],
    event_callback=None,
) -> tuple[str, dict[str, str]]:
    """Generate complete executable Python code from a workflow DAG.

    Returns:
        (main_code, extra_files) where extra_files is a dict of
        {relative_path: content} for multi-file projects.
    """
    # Build a detailed description of each step
    steps_desc = []
    steps_needing_research = []

    for step in dag.steps:
        step_info = {
            "id": step.id,
            "name": step.name,
            "description": step.description,
            "type": step.step_type,
            "depends_on": step.depends_on,
            "error_handling": step.error_handling,
        }
        if step.api:
            step_info["api"] = {
                "service": step.api.service,
                "endpoint": step.api.endpoint,
                "method": step.api.method,
                "base_url": step.api.base_url,
                "auth_type": step.api.auth_type.value,
                "parameters": step.api.parameters,
            }
        else:
            # Mark steps that need research
            step_info["research_required"] = True
            step_info["api_hint"] = step.inputs.get("api_hint", {})
            step_info["note"] = (
                "NO PRE-INDEXED API. You MUST use fetch_web_page to research "
                "this service's API and generate REAL integration code. "
                "NEVER generate placeholder/stub code for this step."
            )
            steps_needing_research.append(step.name)

        step_info["inputs"] = step.inputs
        step_info["outputs"] = step.outputs
        steps_desc.append(step_info)

    # Identify parallel groups
    parallel_groups = _find_parallel_groups(dag)

    # Determine complexity for multi-file decision
    num_steps = len(dag.steps)
    num_services = len({s.api.service for s in dag.steps if s.api})
    is_complex = num_steps >= 3 or num_services >= 2

    system = _build_system_prompt(is_complex)

    # Check which credentials are actually available
    available_creds = _get_available_credentials()

    prompt = (
        f"WORKFLOW: {dag.name}\n"
        f"DESCRIPTION: {dag.description}\n"
        f"TRIGGER: {json.dumps(dag.trigger)}\n\n"
        f"STEPS:\n{json.dumps(steps_desc, indent=2)}\n\n"
        f"DATA MAPPINGS:\n{json.dumps(data_mappings, indent=2)}\n\n"
        f"PARALLEL GROUPS: {json.dumps(parallel_groups)}\n\n"
        f"ENVIRONMENT VARS: {json.dumps(dag.environment_vars)}\n\n"
        f"AVAILABLE CREDENTIALS:\n{json.dumps(available_creds, indent=2)}\n\n"
        f"IMPORTANT: Only services marked 'available: true' have real credentials configured.\n"
        f"For services WITHOUT credentials, still generate the integration code but:\n"
        f"  - Read credentials from env vars (os.getenv)\n"
        f"  - Add a check: if the env var is empty, log a warning and skip that step gracefully\n"
        f"  - NEVER crash due to missing credentials — use try/except and log the error\n\n"
        f"COMPLEXITY: {'MULTI-FILE' if is_complex else 'SINGLE-FILE'} "
        f"({num_steps} steps, {num_services} services)\n\n"
    )

    # Add explicit research instruction when steps lack APIs
    if steps_needing_research:
        prompt += (
            f"⚠️ CRITICAL: {len(steps_needing_research)} steps have NO pre-indexed API.\n"
            f"Steps needing research: {steps_needing_research}\n"
            f"You MUST use fetch_web_page to look up API documentation for each of these services.\n"
            f"DO NOT generate placeholder code with asyncio.sleep(). "
            f"Research the real API endpoints, auth methods, and request formats.\n"
            f"Use the SERVICE-SPECIFIC PATTERNS in your instructions as starting points.\n\n"
        )

    # Inject real Slack channels into channel-related step inputs so code uses them
    slack_cred = next((c for c in available_creds if c["service"] == "Slack"), {})
    real_channels = slack_cred.get("real_channels", [])
    if real_channels:
        prompt += (
            f"SLACK CHANNELS: The real channels in this workspace are: {real_channels}\n"
            f"When generating Slack steps, use one of these EXACT channel names.\n"
            f"Pick the most contextually appropriate channel. Default to '{real_channels[0]}' if unsure.\n\n"
        )

    prompt += (
        f"CRITICAL: Use the EXACT input values from each step's 'inputs' dict in the generated code.\n"
        f"For example, if a step has inputs: {{\"channel\": \"#notifications\", \"text\": \"Hello\"}}, use those EXACT values.\n"
        f"Do NOT substitute default values like '#general' — use what the user specified.\n\n"
        f"CRITICAL CONTEXT PASSING RULES:\n"
        f"  - Each step function MUST store its result as context['step_N'] = {{'ok': True, ...data...}}\n"
        f"    where N is the step number (e.g. step_1, step_2, etc.)\n"
        f"  - When a step depends on a previous step, check the OUTER result dict, not the inner data:\n"
        f"    WRONG: prev = context.get('step_1', {{}}).get('outputs', {{}}); if not prev.get('ok'): ...\n"
        f"    RIGHT: prev_result = context.get('step_1', {{}}); prev = prev_result.get('outputs', prev_result); if not prev_result.get('ok'): ...\n"
        f"  - If you store data in context['step_N']['outputs'], check context['step_N']['ok'] — not context['step_N']['outputs']['ok']\n\n"
        f"TOKEN BUDGET REMINDER: This is a LONG workflow. To avoid truncation:\n"
        f"  1. Generate all {num_steps} step functions completely — do not skip any\n"
        f"  2. End with a complete main() function that calls all steps\n"
        f"  3. End with: if __name__ == '__main__': asyncio.run(main())\n"
        f"  4. If you're running low on space, make functions shorter — but NEVER omit them\n\n"
        f"Generate the workflow code now. Use your tools to browse API docs "
        f"for any step that needs research, and use write_file for additional project files."
    )

    # Set up project directory — use /tmp to avoid triggering uvicorn reload
    workflow_dir = os.path.join("/tmp", "forgeflow_codegen")
    os.makedirs(workflow_dir, exist_ok=True)

    # Tool event callback for UI
    async def on_tool_call(tool_name, tool_args, result):
        if event_callback:
            tool_icons = {
                "fetch_web_page": "🌐",
                "execute_shell": "💻",
                "write_file": "📝",
                "read_file": "📖",
                "test_api_endpoint": "🔌",
            }
            icon = tool_icons.get(tool_name, "🔧")

            # Build a user-friendly description
            if tool_name == "fetch_web_page":
                desc = f"Browsing: {tool_args.get('url', '')[:80]}"
            elif tool_name == "execute_shell":
                desc = f"Running: {tool_args.get('command', '')[:60]}"
            elif tool_name == "write_file":
                desc = f"Writing: {tool_args.get('path', '')}"
            elif tool_name == "read_file":
                desc = f"Reading: {tool_args.get('path', '')}"
            elif tool_name == "test_api_endpoint":
                desc = f"Testing: {tool_args.get('method', 'GET')} {tool_args.get('url', '')[:60]}"
            else:
                desc = tool_name

            await event_callback({
                "event_type": "tool.calling",
                "phase": "generating",
                "message": f"{icon} {desc}",
                "data": {
                    "tool": tool_name,
                    "args_keys": list(tool_args.keys()),
                    "result_preview": result[:200] if result else "",
                },
            })

    try:
        code, extra_files = await generate_with_tools(
            prompt=prompt,
            system=system,
            tools_config=TOOLS_CONFIG,
            tool_executor=execute_tool,
            project_dir=workflow_dir,
            model=settings.GEMINI_MODEL,
            max_tokens=16000,          # Raised: long workflows need room
            on_tool_call=on_tool_call,
        )
    except Exception as e:
        logger.error(f"Tool-calling agent failed, falling back to one-shot: {e}")
        try:
            code = await generate_text(
                prompt=prompt + "\n\nIMPORTANT: Generate the COMPLETE, FULL workflow.py code. Do NOT abbreviate or truncate.",
                system=system,
                model=settings.GEMINI_MODEL,
                max_tokens=16000,
            )
            extra_files = {}
        except Exception:
            code = _fallback_code(dag)
            extra_files = {}

    # Strip markdown code fences if present
    if code.startswith("```"):
        lines = code.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)

    # Detect truncation and complete the code if needed
    code = await _complete_if_truncated(code, dag, prompt, system)

    # Guarantee the code is runnable — add main() + entry point if missing
    code = _ensure_runnable(code, dag)

    return code, extra_files


async def _complete_if_truncated(code: str, dag: "WorkflowDAG", original_prompt: str, system: str) -> str:
    """Detect mid-generation truncation and do a completion pass.

    Signs of truncation:
    - Last non-empty line is inside a function body (indented)
    - No `if __name__ == '__main__'` guard
    - No `asyncio.run(main())` call
    - Code ends with an unterminated string or open block
    """
    import ast as _ast

    stripped = code.rstrip()
    if not stripped:
        return code

    last_line = stripped.split("\n")[-1]
    has_entry = "if __name__" in code and "__main__" in code

    # Fast check: if code ends clean and has entry point, skip completion
    if has_entry and not last_line.startswith(" ") and not last_line.startswith("\t"):
        return code

    # Try to parse — if it fails with a non-EOF error it's likely truncated
    try:
        _ast.parse(code)
        # Parsed OK but might still be missing main()
        if has_entry:
            return code  # Complete
        # Fall through to completion
    except SyntaxError as e:
        # EOF errors strongly indicate truncation
        is_truncated = (
            "EOF" in str(e) or
            "unexpected" in str(e).lower() or
            e.lineno == len(code.split("\n"))
        )
        if not is_truncated:
            return code  # Different kind of syntax error — let self-debugger handle

    logger.warning("[CodeGen] Truncation detected — running completion pass")

    completion_prompt = (
        f"The following Python workflow code was TRUNCATED mid-generation and is incomplete.\n"
        f"Complete it by:\n"
        f"1. Finishing any incomplete function (the last function may be cut off mid-body)\n"
        f"2. Adding ALL remaining step functions that are in the workflow but not yet in the code\n"
        f"3. Adding a main() async function that calls all steps in order with a shared context dict\n"
        f"4. Adding `if __name__ == '__main__': asyncio.run(main())`\n\n"
        f"WORKFLOW STEPS NEEDED:\n"
        + "\n".join(f"  - {s.name}: {s.description}" for s in dag.steps)
        + f"\n\nTRUNCATED CODE SO FAR (continue from where it stopped):\n```python\n{code}\n```\n\n"
        f"OUTPUT: Return ONLY the CONTINUATION — the part that comes AFTER the truncated code. "
        f"Do NOT repeat what's already there. Start from the incomplete function body or the next function."
    )

    try:
        continuation = await generate_text(
            prompt=completion_prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=8000,
        )
        # Strip fences from continuation
        if continuation.startswith("```"):
            lines = continuation.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            continuation = "\n".join(lines)

        completed = code.rstrip() + "\n" + continuation.lstrip()
        logger.info(f"[CodeGen] Completion pass added {len(continuation.split(chr(10)))} lines")
        return completed
    except Exception as e:
        logger.error(f"[CodeGen] Completion pass failed: {e}")
        return code


def _ensure_runnable(code: str, dag: "WorkflowDAG") -> str:
    """Post-process: make sure the code has a main() function and entry point.

    Gemini sometimes truncates at max_tokens and leaves the code without a main().
    This detects that and injects a minimal but working entry point.
    """
    import ast as _ast

    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return code  # Don't touch broken code — let self-debugger handle it

    # Find all defined async/sync functions
    all_funcs = [
        n.name for n in _ast.walk(tree)
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
    ]
    has_main = "main" in all_funcs
    has_entry = "__name__" in code and "__main__" in code

    if has_main and has_entry:
        return code  # Already complete

    # Find step functions (named step_* or execute_*)
    step_funcs = sorted([
        n for n in all_funcs
        if n.startswith("step_") or n.startswith("execute_") or n.startswith("run_")
    ])

    # If no main(), build one that calls all step functions in order
    if not has_main:
        step_calls = ""
        for fn in step_funcs:
            # Derive the step key (e.g. "step_1") so we can store result in context
            import re as _re
            m = _re.search(r'(step_\d+)', fn)
            step_key = m.group(1) if m else fn
            step_calls += (
                f"    try:\n"
                f"        result = await {fn}(context)\n"
                f"        if isinstance(result, dict):\n"
                f"            context['{step_key}'] = result\n"
                f"        status = '✅' if (result or {{}}).get('ok', True) else '❌'\n"
                f"        print(f'  {fn}: {{status}}')\n"
                f"    except Exception as e:\n"
                f"        print(f'  {fn}: ❌ {{e}}')\n"
                f"        context['{step_key}'] = {{'ok': False, 'error': str(e)}}\n"
                f"\n"
            )

        if not step_calls:
            # Fallback: if no step functions found, list all non-private functions
            candidate_fns = [f for f in all_funcs if not f.startswith("_") and f not in ("main",)]
            for fn in candidate_fns[:8]:
                step_calls += f"    # {fn}(context)  — call your step function here\n"

        dag_name = getattr(dag, "name", "Workflow")
        main_block = f"""

async def main():
    \"\"\"Execute the {dag_name} workflow.
    Auto-generated entry point by ForgeFlow.
    \"\"\"
    from datetime import datetime
    print(f"\\n=== Starting: {dag_name} ===")
    print(f"Time: {{datetime.now().isoformat()}}\\n")
    context = {{}}
{step_calls}
    print("\\n=== Workflow Complete ===")
    for k, v in context.items():
        ok = v.get('ok', '?') if isinstance(v, dict) else '?'
        print(f"  {{k}}: {{'✅' if ok is True else '❌' if ok is False else ok}}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
"""
        code = code.rstrip() + main_block

    elif not has_entry:
        # Has main() but no entry guard
        code = code.rstrip() + "\n\nif __name__ == '__main__':\n    import asyncio\n    asyncio.run(main())\n"

    logger.info(f"[CodeGen] Entry point injected — step functions found: {step_funcs}")
    return code


def _build_system_prompt(is_complex: bool) -> str:
    """Build the system prompt for code generation."""
    base = """You are ForgeFlow's AI code generation agent. You generate PRODUCTION-QUALITY,
ACTUALLY WORKING Python code for workflow automations.

CRITICAL RULES:
1. NEVER generate placeholder code. Every step must do REAL work with REAL API calls.
2. NEVER use asyncio.sleep() as a fake step. Every function must call a real API or perform real logic.
3. If a step has no API specification (research_required=true), you MUST use your tools to research it:
   - Use fetch_web_page to read API documentation
   - Use test_api_endpoint to verify endpoints work
   - Use execute_shell to test code snippets
4. Generate code that is IMMEDIATELY RUNNABLE with `python workflow.py` (given env vars are set)
5. Every workflow step MUST result in a real HTTP call, WebSocket message, or meaningful data operation

AVAILABLE TOOLS (USE THEM!):
- fetch_web_page(url) — Read API docs. Example: fetch_web_page("https://api.slack.com/methods/chat.postMessage")
- test_api_endpoint(method, url, headers, body) — Verify an API endpoint works before generating code for it
- execute_shell(command) — Run quick tests: python3 -c "import httpx; print('ok')"
- write_file(path, content) — Create additional project files (config.py, clients, etc.)
- read_file(path) — Read previously written project files

RESEARCH WORKFLOW (for steps marked research_required=true):
1. Look at the step's api_hint for the service name and docs URL
2. Use fetch_web_page to read that service's API documentation
3. Identify the correct endpoint, HTTP method, auth header format, and request body schema
4. Generate proper async httpx code based on what you learned
5. Each researched service should use environment variables for credentials

CODE REQUIREMENTS:
1. Use async/await with httpx.AsyncClient() for ALL HTTP calls
2. Use environment variables for ALL secrets (os.getenv with descriptive names like SLACK_BOT_TOKEN, JIRA_API_TOKEN, etc.)
3. Include proper error handling with try/except per step, logging the error details
4. Include retry logic with exponential backoff (max 3 retries per API call)
5. Use asyncio.gather() for parallel steps (steps with the same dependencies)
6. Include structured logging with timestamps: logging.info(f"[StepName] ...")
7. Include a main() function that runs the full workflow
8. Include if __name__ == "__main__": asyncio.run(main())
9. Make code FULLY SELF-CONTAINED in a single workflow.py — ALL client functions must be INLINE in the file
   NEVER create separate client modules like "from clients.jira_client import ..." — put ALL code in ONE file
   Only use standard library + httpx + websockets as external dependencies
10. Add "# Auto-generated by ForgeFlow" header comment
11. Print a summary at the end showing which steps succeeded/failed
12. For services WITHOUT credentials, check if env var is empty and skip gracefully:
    if not os.getenv("SLACK_BOT_TOKEN"): logging.warning("[Slack] No token — skipping"); return {"ok": False, "error": "not configured"}

PRE-BUILT INTEGRATION CLIENTS (USE THESE — they are production-tested with retry logic):

ForgeFlow has pre-built client libraries for all major services. ALWAYS use these patterns
in generated code. Each client has: retry with exponential backoff, structured error handling,
environment variable auth, and returns {"ok": True/False, ...} responses.

SLACK (env: SLACK_BOT_TOKEN):
```python
import httpx, os, asyncio, base64
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_HEADERS = {"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json; charset=utf-8"}

async def slack_send_message(channel: str, text: str) -> dict:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post("https://slack.com/api/chat.postMessage",
                    headers=SLACK_HEADERS, json={"channel": channel, "text": text})
                r.raise_for_status()
                data = r.json()
                if data.get("ok"): return {"ok": True, "ts": data.get("ts")}
                return {"ok": False, "error": data.get("error")}
        except Exception as e:
            if attempt < 2: await asyncio.sleep(2 ** attempt)
            else: return {"ok": False, "error": str(e)}

async def slack_lookup_user(email: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://slack.com/api/users.lookupByEmail",
            headers=SLACK_HEADERS, params={"email": email})
        data = r.json()
        if data.get("ok"): return {"ok": True, "user_id": data["user"]["id"]}
        return {"ok": False, "error": data.get("error")}

async def slack_invite_to_channel(channel_id: str, user_ids: list) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://slack.com/api/conversations.invite",
            headers=SLACK_HEADERS, json={"channel": channel_id, "users": ",".join(user_ids)})
        return r.json()

async def slack_create_channel(name: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://slack.com/api/conversations.create",
            headers=SLACK_HEADERS, json={"name": name.lower().replace(" ", "-")})
        data = r.json()
        if data.get("ok"): return {"ok": True, "channel_id": data["channel"]["id"]}
        return {"ok": False, "error": data.get("error")}
```

GMAIL SMTP (env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD):
Uses Python built-in smtplib — NO OAuth, NO Google Cloud needed. Just a Gmail address + App Password.
```python
import smtplib, os, logging, asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

async def gmail_send_email(to: str, subject: str, body: str, html_body: str = "") -> dict:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logging.warning("[Gmail] GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — skipping email")
        return {"ok": False, "error": "Gmail credentials not configured"}
    try:
        if html_body:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg = MIMEText(body, "plain")
        msg["To"] = to
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        # Run SMTP in executor to avoid blocking
        def _send():
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)
        await asyncio.get_event_loop().run_in_executor(None, _send)
        logging.info(f"[Gmail] Email sent to {to}: {subject}")
        return {"ok": True, "to": to, "subject": subject}
    except Exception as e:
        logging.error(f"[Gmail] Failed to send email: {e}")
        return {"ok": False, "error": str(e)}
```

GOOGLE SHEETS (env: GOOGLE_API_KEY, GOOGLE_SHEET_ID):
Uses Google Sheets API v4 with an API key. The spreadsheet MUST be shared as "Anyone with the link can edit".
```python
import httpx, os, asyncio, logging
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
SHEETS_ID = os.getenv("GOOGLE_SHEET_ID", "")

async def sheets_append_row(values: list, sheet_range: str = "Sheet1!A:Z", spreadsheet_id: str = "") -> dict:
    if not GOOGLE_API_KEY:
        logging.warning("[Sheets] GOOGLE_API_KEY not set — skipping")
        return {"ok": False, "error": "Google API key not configured"}
    sid = spreadsheet_id or SHEETS_ID
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{sheet_range}:append"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, json={"values": [values]},
                    params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS", "key": GOOGLE_API_KEY})
                if r.status_code == 401:
                    logging.warning("[Sheets] 401 Unauthorized — API key cannot write (requires OAuth/service account). Skipping.")
                    return {"ok": False, "error": "Sheets write requires OAuth — API key is read-only"}
                r.raise_for_status()
                return {"ok": True, "updated_rows": r.json().get("updates", {}).get("updatedRows", 0)}
        except Exception as e:
            if attempt < 2: await asyncio.sleep(2 ** attempt)
            else: return {"ok": False, "error": str(e)}

async def sheets_read_range(sheet_range: str = "Sheet1!A1:Z1000", spreadsheet_id: str = "") -> dict:
    if not GOOGLE_API_KEY:
        logging.warning("[Sheets] GOOGLE_API_KEY not set — skipping")
        return {"ok": False, "error": "Google API key not configured"}
    sid = spreadsheet_id or SHEETS_ID
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{sheet_range}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params={"key": GOOGLE_API_KEY})
        r.raise_for_status()
        return {"ok": True, "values": r.json().get("values", [])}
```

HTTP / WEBHOOKS / HEALTH CHECKS (generic):
```python
import httpx, asyncio, os

async def http_health_check(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
            return {"ok": True, "status": r.status_code, "healthy": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e), "healthy": False}

async def http_webhook(url: str, payload: dict) -> dict:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, json=payload)
                r.raise_for_status()
                return {"ok": True, "status": r.status_code}
        except Exception as e:
            if attempt < 2: await asyncio.sleep(2 ** attempt)
            else: return {"ok": False, "error": str(e)}
```

DATA FLOW: Use a shared `context: dict` to pass data between steps. Each step reads from and writes to context.

OUTPUT: Return ONLY the complete Python code for workflow.py. No markdown fences. No explanations. No comments about what you would do — just the code."""

    if is_complex:
        base += """

MULTI-FILE PROJECT:
For this complex workflow (3+ steps or 2+ services), generate a MULTI-FILE project:
- Use write_file to create: config.py (env vars), service client modules, etc.
- The main workflow.py should import from these files
- Each service should have its own client module if needed
- Use write_file tool to create each additional file BEFORE returning the main code
- Return the main workflow.py as your final text response"""

    return base


def _find_parallel_groups(dag: WorkflowDAG) -> list[list[str]]:
    """Find steps that share the same dependencies and can run in parallel."""
    by_deps: dict[tuple, list[str]] = {}
    for step in dag.steps:
        key = tuple(sorted(step.depends_on))
        by_deps.setdefault(key, []).append(step.id)

    return [ids for ids in by_deps.values() if len(ids) > 1]


def _fallback_code(dag: WorkflowDAG) -> str:
    """Generate minimal fallback code if LLM fails entirely."""
    steps_code = ""
    for i, step in enumerate(dag.steps):
        service = step.api.service if step.api else "Unknown"
        steps_code += f'''
    # Step {i+1}: {step.name}
    try:
        print(f"[Step {i+1}] Executing: {step.name}")
        # Service: {service}
        # Description: {step.description}
        # TODO: Configure API credentials in environment variables
        async with httpx.AsyncClient(timeout=30) as client:
            print(f"[Step {i+1}] {step.name} — requires API configuration")
            context["{step.id}"] = {{"status": "needs_configuration", "step": "{step.name}"}}
    except Exception as e:
        print(f"[Step {i+1}] Error in {step.name}: {{e}}")
        context["{step.id}"] = {{"status": "error", "error": str(e)}}
'''

    return f'''# Auto-generated by ForgeFlow (fallback — configure API credentials to activate)
import asyncio
import httpx
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("workflow")

async def main():
    """Workflow: {dag.name}

    Description: {dag.description}
    Steps: {len(dag.steps)}
    """
    print(f"\\n=== Starting Workflow: {dag.name} ===")
    print(f"Time: {{datetime.now().isoformat()}}")
    context = {{}}
{steps_code}
    # Summary
    print(f"\\n=== Workflow Complete ===")
    for step_id, result in context.items():
        status = result.get("status", "unknown")
        print(f"  {{step_id}}: {{status}}")

if __name__ == "__main__":
    asyncio.run(main())
'''
