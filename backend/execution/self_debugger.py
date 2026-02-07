"""Self-debugging loop — THE SHOWSTOPPER.

Analyzes failures, diagnoses root causes, and generates targeted fixes.
Uses AST-based error parsing for structured diagnostics.
Runs up to 3 iterations autonomously.
"""

from backend.shared.config import settings
from backend.shared.gemini_client import generate_json
from backend.shared.models import DebugDiagnosis
from backend.execution.error_parser import parse_error, find_undefined_names


async def diagnose_and_fix(
    code: str,
    error: str,
    stderr: str = "",
    attempt: int = 1,
) -> DebugDiagnosis:
    """Analyze failure and generate a targeted code fix.

    Uses AST-based error parsing to provide structured context
    to the LLM for more targeted fixes.

    Args:
        code: The full generated code that failed
        error: The error message
        stderr: Full stderr output including traceback
        attempt: Current debug attempt (1-3)

    Returns:
        DebugDiagnosis with category, root cause, and fixed code
    """
    # ── STRUCTURED ERROR PARSING ──
    parsed = parse_error(stderr or error, code)
    undefined_names = find_undefined_names(code)

    # Build a rich, structured prompt with parsed error info
    structured_info = (
        f"ERROR TYPE: {parsed.error_type}\n"
        f"ERROR MESSAGE: {parsed.message}\n"
        f"CATEGORY (pre-classified): {parsed.category}\n"
    )

    if parsed.line_number:
        structured_info += f"LINE NUMBER: {parsed.line_number}\n"

    if parsed.code_context:
        structured_info += f"\nCODE CONTEXT (around error line):\n{parsed.code_context}\n"

    if parsed.traceback_frames:
        structured_info += "\nTRACEBACK FRAMES:\n"
        for frame in parsed.traceback_frames[-5:]:  # Last 5 frames
            structured_info += f"  {frame['file']}:{frame['line']} in {frame['function']}\n"

    if parsed.suggestions:
        structured_info += "\nSUGGESTED FIX STRATEGIES:\n"
        for s in parsed.suggestions:
            structured_info += f"  - {s}\n"

    if undefined_names:
        structured_info += f"\nUNDEFINED NAMES DETECTED (AST analysis): {', '.join(undefined_names)}\n"

    system = """You are ForgeFlow's self-debugging engine. Analyze the code failure and generate a targeted fix.

DIAGNOSIS CATEGORIES:
- AUTH_ERROR: Authentication/credentials issue (wrong token format, expired, missing)
- SCHEMA_MISMATCH: API request/response format is wrong (wrong data types, missing fields, wrong nesting)
- RATE_LIMIT: API rate limiting (need backoff/retry)
- MISSING_PARAM: Required parameter not provided
- LOGIC_ERROR: Code logic issue (wrong variable, bad condition, import error)
- NETWORK_ERROR: Connectivity issue (timeout, DNS, unreachable)
- IMPORT_ERROR: Missing import or module not found
- SYNTAX_ERROR: Python syntax error (bad indentation, missing colon, etc.)

RULES:
1. Use the STRUCTURED ERROR INFO to pinpoint the exact issue
2. The error has been pre-classified — use that as a strong hint
3. Generate the COMPLETE fixed code (not just the diff) — the entire file must be returned
4. Only change what's necessary to fix the issue
5. If it's an import error, add the missing import
6. If it's a schema mismatch, fix the data structure
7. If it's an auth error, fix the auth header/token format
8. If undefined names are listed, fix those references
9. Keep all the original functionality intact

OUTPUT ONLY valid JSON:
{
    "category": "one of the categories above",
    "root_cause": "specific root cause description",
    "fix_description": "what was changed to fix it",
    "fixed_function": "THE COMPLETE FIXED CODE (entire file)",
    "diff": "human-readable description of changes"
}"""

    prompt = (
        f"ATTEMPT: {attempt}/{settings.MAX_DEBUG_ATTEMPTS}\n\n"
        f"=== STRUCTURED ERROR ANALYSIS ===\n{structured_info}\n\n"
        f"=== FULL CODE ===\n```python\n{code}\n```\n\n"
        f"=== RAW ERROR ===\n{error}\n\n"
        f"=== RAW STDERR ===\n{stderr}\n\n"
        "Diagnose and fix."
    )

    try:
        result = await generate_json(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=8192,
        )
        if result:
            return DebugDiagnosis(
                category=result.get("category", parsed.category),
                root_cause=result.get("root_cause", "Unknown"),
                fix_description=result.get("fix_description", ""),
                fixed_function=result.get("fixed_function", code),
                diff=result.get("diff", ""),
            )
    except Exception as e:
        print(f"[SelfDebug] Diagnosis error: {e}")

    return DebugDiagnosis(
        category=parsed.category or "LOGIC_ERROR",
        root_cause=parsed.message or "Could not parse debug response",
        fix_description="Unable to auto-fix",
        fixed_function=code,
        diff="No changes made",
    )
