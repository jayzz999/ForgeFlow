"""AST-based error parser for structured debugging.

Parses Python errors into structured diagnostics, validates syntax
before execution, and finds undefined names — giving the self-debugger
much more targeted information than raw stderr.
"""

import ast
import re
import traceback
from dataclasses import dataclass, field


@dataclass
class ParsedError:
    """Structured error information."""
    error_type: str = ""
    message: str = ""
    line_number: int | None = None
    code_context: str = ""
    traceback_frames: list[dict] = field(default_factory=list)
    category: str = "UNKNOWN"
    suggestions: list[str] = field(default_factory=list)


# ── Error Categories ─────────────────────────────────────────

ERROR_CATEGORIES = {
    "ModuleNotFoundError": "IMPORT_ERROR",
    "ImportError": "IMPORT_ERROR",
    "SyntaxError": "SYNTAX_ERROR",
    "IndentationError": "SYNTAX_ERROR",
    "TabError": "SYNTAX_ERROR",
    "NameError": "LOGIC_ERROR",
    "AttributeError": "LOGIC_ERROR",
    "TypeError": "LOGIC_ERROR",
    "ValueError": "LOGIC_ERROR",
    "KeyError": "SCHEMA_MISMATCH",
    "IndexError": "LOGIC_ERROR",
    "ConnectionError": "NETWORK_ERROR",
    "TimeoutError": "NETWORK_ERROR",
    "httpx.ConnectError": "NETWORK_ERROR",
    "httpx.ReadTimeout": "NETWORK_ERROR",
    "aiohttp.ClientError": "NETWORK_ERROR",
    "PermissionError": "AUTH_ERROR",
    "FileNotFoundError": "MISSING_PARAM",
    "JSONDecodeError": "SCHEMA_MISMATCH",
    "json.decoder.JSONDecodeError": "SCHEMA_MISMATCH",
    "ssl.SSLError": "NETWORK_ERROR",
}

AUTH_KEYWORDS = ["401", "403", "unauthorized", "forbidden", "invalid_auth", "token", "credential"]
RATE_LIMIT_KEYWORDS = ["429", "rate limit", "too many requests", "throttl"]


def categorize_error(error_type: str, message: str) -> str:
    """Determine the error category from type and message."""
    # Check direct mapping first
    if error_type in ERROR_CATEGORIES:
        cat = ERROR_CATEGORIES[error_type]
    else:
        cat = "LOGIC_ERROR"

    # Override with semantic analysis
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in AUTH_KEYWORDS):
        return "AUTH_ERROR"
    if any(kw in msg_lower for kw in RATE_LIMIT_KEYWORDS):
        return "RATE_LIMIT"

    return cat


# ── Parse Error from Stderr ──────────────────────────────────

def parse_error(stderr: str, code: str = "") -> ParsedError:
    """Parse stderr output into a structured ParsedError.

    Args:
        stderr: Raw stderr from subprocess execution
        code: The source code that produced the error

    Returns:
        ParsedError with structured fields
    """
    if not stderr:
        return ParsedError(message="No error output", category="UNKNOWN")

    error = ParsedError()
    lines = stderr.strip().split("\n")

    # Extract the final error line (usually last line)
    error_line = ""
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("During handling"):
            error_line = line
            break

    # Parse error type and message
    if ": " in error_line:
        parts = error_line.split(": ", 1)
        error.error_type = parts[0].strip()
        error.message = parts[1].strip()
    else:
        error.message = error_line

    # Parse traceback frames
    frame_pattern = re.compile(
        r'File "([^"]+)", line (\d+)(?:, in (.+))?'
    )
    for match in frame_pattern.finditer(stderr):
        filename = match.group(1)
        line_num = int(match.group(2))
        func_name = match.group(3) or "<module>"
        error.traceback_frames.append({
            "file": filename,
            "line": line_num,
            "function": func_name,
        })
        # Use the last frame's line number
        error.line_number = line_num

    # Extract code context around the error line
    if error.line_number and code:
        code_lines = code.split("\n")
        start = max(0, error.line_number - 3)
        end = min(len(code_lines), error.line_number + 2)
        context_lines = []
        for i in range(start, end):
            marker = " >> " if i == error.line_number - 1 else "    "
            context_lines.append(f"{marker}{i + 1}: {code_lines[i]}")
        error.code_context = "\n".join(context_lines)

    # Categorize
    error.category = categorize_error(error.error_type, error.message)

    # Generate suggestions
    error.suggestions = _suggest_fixes(error)

    return error


# ── Syntax Validation ─────────────────────────────────────────

def validate_syntax(code: str) -> ParsedError | None:
    """Validate Python syntax using AST.

    Returns None if syntax is valid, or ParsedError with details.
    """
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        error = ParsedError(
            error_type="SyntaxError",
            message=str(e.msg) if e.msg else str(e),
            line_number=e.lineno,
            category="SYNTAX_ERROR",
        )

        # Extract context
        if e.lineno and code:
            code_lines = code.split("\n")
            start = max(0, e.lineno - 3)
            end = min(len(code_lines), e.lineno + 2)
            context_lines = []
            for i in range(start, end):
                marker = " >> " if i == e.lineno - 1 else "    "
                if i < len(code_lines):
                    context_lines.append(f"{marker}{i + 1}: {code_lines[i]}")
            error.code_context = "\n".join(context_lines)

        error.suggestions = [
            f"Syntax error at line {e.lineno}: {e.msg}",
            "Check for mismatched brackets, missing colons, or invalid indentation",
        ]

        return error


# ── Find Undefined Names ──────────────────────────────────────

def find_undefined_names(code: str) -> list[str]:
    """Walk AST to find names that are used but never defined or imported.

    This is a best-effort analysis — it won't catch all cases but
    catches common ones like misspelled variable names.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    # Collect all defined names (assignments, imports, function defs, class defs)
    defined = set()
    # Python builtins
    import builtins
    defined.update(dir(builtins))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            defined.add(node.name)
            for arg in node.args.args:
                defined.add(arg.arg)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    _collect_names(target, defined)
            elif node.target:
                _collect_names(node.target, defined)
        elif isinstance(node, ast.For):
            _collect_names(node.target, defined)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    _collect_names(item.optional_vars, defined)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                defined.add(node.name)

    # Collect all referenced names
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    # Find undefined (used but not defined)
    undefined = sorted(used - defined)
    return undefined


def _collect_names(node: ast.AST, names: set):
    """Recursively collect assigned names from AST node."""
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Tuple | ast.List):
        for elt in node.elts:
            _collect_names(elt, names)
    elif isinstance(node, ast.Starred):
        _collect_names(node.value, names)


# ── Fix Suggestions ───────────────────────────────────────────

def _suggest_fixes(error: ParsedError) -> list[str]:
    """Generate fix suggestions based on error category."""
    suggestions = []

    if error.category == "IMPORT_ERROR":
        module = error.message.split("'")[1] if "'" in error.message else error.message
        suggestions.append(f"Install the missing module: pip install {module}")
        suggestions.append("Check if the module name is spelled correctly")
        suggestions.append("Verify the module is compatible with your Python version")

    elif error.category == "SYNTAX_ERROR":
        suggestions.append("Check for mismatched parentheses, brackets, or quotes")
        suggestions.append("Verify indentation is consistent (spaces vs tabs)")
        if error.line_number:
            suggestions.append(f"Focus on line {error.line_number} and the line before it")

    elif error.category == "AUTH_ERROR":
        suggestions.append("Verify the API token/key is correct and not expired")
        suggestions.append("Check the Authorization header format (Bearer vs Basic)")
        suggestions.append("Ensure the token has the required scopes/permissions")

    elif error.category == "SCHEMA_MISMATCH":
        suggestions.append("Check the API response format — it may have changed")
        suggestions.append("Verify the request body structure matches the API spec")
        suggestions.append("Add response validation and defensive access (dict.get())")

    elif error.category == "NETWORK_ERROR":
        suggestions.append("Verify the API URL is correct and reachable")
        suggestions.append("Add retry logic with exponential backoff")
        suggestions.append("Check if the API requires specific network settings")

    elif error.category == "RATE_LIMIT":
        suggestions.append("Add delays between API calls (asyncio.sleep)")
        suggestions.append("Implement exponential backoff retry logic")
        suggestions.append("Check API documentation for rate limit windows")

    elif error.category == "LOGIC_ERROR":
        suggestions.append("Check variable names for typos")
        suggestions.append("Verify function arguments match the expected signature")
        suggestions.append("Add debug print statements to trace the logic flow")

    return suggestions
