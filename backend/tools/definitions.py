"""Tool definitions for the ForgeFlow agent.

These are Gemini function declarations that the LLM can invoke during
code generation. This transforms ForgeFlow from a one-shot generator
into an interactive agent that can browse docs, test APIs, and write
multi-file projects.
"""

from google.genai import types


# ── Tool 1: Fetch Web Page ────────────────────────────────────

fetch_web_page_decl = types.FunctionDeclaration(
    name="fetch_web_page",
    description=(
        "Fetch a web page and return its text content. "
        "Use this to read API documentation, code examples, README files, "
        "or any online resource needed for code generation. "
        "Useful for verifying endpoint URLs, checking request/response schemas, "
        "and reading library docs."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "url": types.Schema(
                type=types.Type.STRING,
                description="The URL to fetch (must be https or http).",
            ),
            "extract_code": types.Schema(
                type=types.Type.BOOLEAN,
                description="If true, extract only code blocks from the page. Default false.",
            ),
        },
        required=["url"],
    ),
)

# ── Tool 2: Execute Shell Command ─────────────────────────────

execute_shell_decl = types.FunctionDeclaration(
    name="execute_shell",
    description=(
        "Execute a shell command and return stdout/stderr. "
        "Use this to test code snippets, install packages, run scripts, "
        "check environment, or validate syntax. "
        "Commands have a 30-second timeout. Dangerous commands are blocked."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "command": types.Schema(
                type=types.Type.STRING,
                description="The shell command to execute.",
            ),
            "timeout": types.Schema(
                type=types.Type.INTEGER,
                description="Timeout in seconds (default 30, max 60).",
            ),
        },
        required=["command"],
    ),
)

# ── Tool 3: Write File ────────────────────────────────────────

write_file_decl = types.FunctionDeclaration(
    name="write_file",
    description=(
        "Write content to a file in the workflow project directory. "
        "Use this to create multi-file projects: config.py, api_clients/, "
        "tests/, Dockerfile, docker-compose.yml, etc. "
        "The path is relative to the project root."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "path": types.Schema(
                type=types.Type.STRING,
                description="Relative file path within the project (e.g. 'config.py', 'clients/slack.py').",
            ),
            "content": types.Schema(
                type=types.Type.STRING,
                description="The full file content to write.",
            ),
        },
        required=["path", "content"],
    ),
)

# ── Tool 4: Read File ─────────────────────────────────────────

read_file_decl = types.FunctionDeclaration(
    name="read_file",
    description=(
        "Read the contents of a file from the project directory. "
        "Use this to review previously written files, check existing code, "
        "or read configuration."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "path": types.Schema(
                type=types.Type.STRING,
                description="Relative file path within the project to read.",
            ),
        },
        required=["path"],
    ),
)

# ── Tool 5: Test API Endpoint ──────────────────────────────────

test_api_endpoint_decl = types.FunctionDeclaration(
    name="test_api_endpoint",
    description=(
        "Make an HTTP request to test an API endpoint. "
        "Use this to verify that an API is reachable, check response format, "
        "test authentication, or explore available endpoints. "
        "Returns the HTTP status code and response body."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "method": types.Schema(
                type=types.Type.STRING,
                description="HTTP method: GET, POST, PUT, DELETE, PATCH.",
            ),
            "url": types.Schema(
                type=types.Type.STRING,
                description="The full URL to request.",
            ),
            "headers": types.Schema(
                type=types.Type.STRING,
                description='JSON string of headers, e.g. \'{"Authorization": "Bearer xxx"}\'.',
            ),
            "body": types.Schema(
                type=types.Type.STRING,
                description="JSON string of the request body (for POST/PUT/PATCH).",
            ),
        },
        required=["method", "url"],
    ),
)


# ── All Tools ──────────────────────────────────────────────────

ALL_TOOL_DECLARATIONS = [
    fetch_web_page_decl,
    execute_shell_decl,
    write_file_decl,
    read_file_decl,
    test_api_endpoint_decl,
]

TOOLS_CONFIG = types.Tool(function_declarations=ALL_TOOL_DECLARATIONS)
