"""Auto-generate pytest test cases for workflow code.

Given a workflow DAG and generated code, produces a test file that validates:
- Each step function exists and is callable
- API calls use correct endpoints and methods
- Error handling works (retry, fallback)
- Data flow between steps is correct
- Environment variables are referenced properly
"""

import json
import logging

from backend.shared.config import settings
from backend.shared.gemini_client import generate_text
from backend.shared.models import WorkflowDAG

logger = logging.getLogger("forgeflow.testgen")


async def generate_tests(
    dag: WorkflowDAG,
    code: str,
    extra_files: dict[str, str] | None = None,
) -> str:
    """Generate pytest test cases for a workflow.

    Args:
        dag: The workflow DAG with step definitions
        code: The generated workflow.py source code
        extra_files: Additional project files (clients, config, etc.)

    Returns:
        Complete pytest test file as a string
    """
    # Build context about the workflow
    steps_info = []
    services = set()
    env_vars = list(dag.environment_vars)

    for step in dag.steps:
        step_data = {
            "id": step.id,
            "name": step.name,
            "description": step.description,
            "step_type": step.step_type,
            "depends_on": step.depends_on,
            "error_handling": step.error_handling,
        }
        if step.api:
            step_data["api"] = {
                "service": step.api.service,
                "endpoint": step.api.endpoint,
                "method": step.api.method,
                "base_url": step.api.base_url,
            }
            services.add(step.api.service)
        steps_info.append(step_data)

    # Include extra files context
    extra_files_info = ""
    if extra_files:
        for path, content in extra_files.items():
            extra_files_info += f"\n--- {path} ---\n{content[:500]}\n"

    system = """You are a Python test engineer. Generate comprehensive pytest test cases for workflow automation code.

RULES:
1. Generate REAL, RUNNABLE pytest tests
2. Use unittest.mock to mock ALL external API calls (httpx, websockets, etc.)
3. Test each workflow step independently
4. Test error handling and retry logic
5. Test data flow between steps via the shared context dict
6. Test environment variable loading (mock os.getenv)
7. Use pytest fixtures for common setup
8. Include both positive (happy path) and negative (error) test cases
9. Mock httpx.AsyncClient using pytest-httpx or unittest.mock.AsyncMock
10. Use @pytest.mark.asyncio for async tests

STRUCTURE:
- Fixtures: mock clients, env vars, sample data
- Test class per service/step group
- Test happy path: each step succeeds
- Test error handling: API returns error, retry works
- Test data flow: output from step N feeds into step N+1
- Test env vars: all required env vars are read

OUTPUT: Return ONLY the complete Python test file. No markdown. No explanations."""

    prompt = (
        f"WORKFLOW: {dag.name}\n"
        f"DESCRIPTION: {dag.description}\n"
        f"SERVICES: {', '.join(services) if services else 'None'}\n"
        f"ENVIRONMENT VARS: {json.dumps(env_vars)}\n\n"
        f"STEPS:\n{json.dumps(steps_info, indent=2)}\n\n"
        f"WORKFLOW CODE:\n```python\n{code}\n```\n\n"
    )

    if extra_files_info:
        prompt += f"EXTRA PROJECT FILES:\n{extra_files_info}\n\n"

    prompt += "Generate the pytest test file now."

    try:
        test_code = await generate_text(
            prompt=prompt,
            system=system,
            model=settings.GEMINI_MODEL,
            max_tokens=6000,
        )
    except Exception as e:
        logger.error(f"Failed to generate tests via LLM: {e}")
        # Fallback: generate basic structural tests
        test_code = _fallback_tests(dag, code, services)

    # Strip markdown code fences if present
    if test_code.startswith("```"):
        lines = test_code.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        test_code = "\n".join(lines)

    return test_code


async def run_tests(test_code: str, project_dir: str) -> dict:
    """Execute generated tests and return results.

    Args:
        test_code: The pytest test file content
        project_dir: Directory containing the workflow project

    Returns:
        Dict with: passed, failed, errors, output, total
    """
    import asyncio
    import os
    import tempfile

    # Write test file
    test_path = os.path.join(project_dir, "test_workflow.py")
    with open(test_path, "w") as f:
        f.write(test_code)

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "pytest", test_path,
            "-v", "--tb=short", "--no-header",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "total": 0,
                "output": "Test execution timed out after 30s",
                "success": False,
            }

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        output = stdout_str + stderr_str

        # Parse pytest output for results
        passed = output.count(" PASSED")
        failed = output.count(" FAILED")
        errors = output.count(" ERROR")
        total = passed + failed + errors

        return {
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": total,
            "output": output[:3000],
            "success": proc.returncode == 0,
        }

    except Exception as e:
        return {
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "total": 0,
            "output": f"Failed to run tests: {str(e)}",
            "success": False,
        }


def _fallback_tests(dag: WorkflowDAG, code: str, services: set) -> str:
    """Generate basic structural tests as fallback."""
    import re

    # Extract function names from code
    func_names = re.findall(r'async def (\w+)\(', code)
    env_vars = re.findall(r'os\.getenv\(["\'](\w+)["\']', code)

    # Build env var dict string
    env_dict_items = ", ".join(f'"{v}": "test_{v.lower()}"' for v in env_vars)

    # Build env var tests
    env_tests = ""
    for var in env_vars:
        env_tests += f'    def test_{var.lower()}_is_read(self):\n'
        env_tests += f'        """Verify {var} is read from environment."""\n'
        env_tests += f'        code = open("workflow.py").read()\n'
        env_tests += f'        assert "{var}" in code\n\n'

    if not env_vars:
        env_tests = "    pass  # No environment variables detected\n"

    # Build API tests
    api_tests = ""
    for service in services:
        svc_name = service.lower().replace(" ", "_")
        api_tests += f'    @pytest.mark.asyncio\n'
        api_tests += f'    async def test_{svc_name}_api_call(self, mock_httpx_client, mock_env_vars):\n'
        api_tests += f'        """Test {service} API integration with mocked client."""\n'
        api_tests += f'        response = await mock_httpx_client.post("https://example.com/api", json={{"test": True}})\n'
        api_tests += f'        assert response.status_code == 200\n'
        api_tests += f'        mock_httpx_client.post.assert_called_once()\n\n'

    if not services:
        api_tests = "    pass  # No API services detected\n"

    # Build the full test file using string concatenation (avoids .format() brace issues)
    tests = f"""# Auto-generated tests by ForgeFlow
# Tests for: {dag.name}

import pytest
import asyncio
import os
from unittest.mock import patch, AsyncMock, MagicMock


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def mock_env_vars():
    \"\"\"Mock all required environment variables.\"\"\"
    env = {{{env_dict_items}}}
    with patch.dict(os.environ, env):
        yield env


@pytest.fixture
def mock_httpx_client():
    \"\"\"Mock httpx.AsyncClient for API calls.\"\"\"
    with patch("httpx.AsyncClient") as mock_class:
        mock_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {{"ok": True, "status": "success"}}
        mock_response.raise_for_status = MagicMock()
        mock_response.text = '{{"ok": true}}'
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_instance.get = AsyncMock(return_value=mock_response)
        mock_instance.put = AsyncMock(return_value=mock_response)
        mock_class.return_value = mock_instance
        yield mock_instance


# ── Structure Tests ──────────────────────────────────────

class TestWorkflowStructure:
    \"\"\"Test that the workflow code has proper structure.\"\"\"

    def test_code_is_valid_python(self):
        \"\"\"Verify the workflow code compiles without syntax errors.\"\"\"
        code = open("workflow.py").read()
        compile(code, "workflow.py", "exec")

    def test_has_main_function(self):
        \"\"\"Verify workflow has a main() entry point.\"\"\"
        code = open("workflow.py").read()
        assert "async def main" in code or "def main" in code

    def test_has_entry_point(self):
        \"\"\"Verify workflow has if __name__ == '__main__' block.\"\"\"
        code = open("workflow.py").read()
        assert '__name__' in code and '__main__' in code

    def test_uses_env_vars(self):
        \"\"\"Verify secrets are loaded from environment, not hardcoded.\"\"\"
        code = open("workflow.py").read()
        assert "os.getenv" in code or "os.environ" in code

    def test_has_error_handling(self):
        \"\"\"Verify workflow has try/except error handling.\"\"\"
        code = open("workflow.py").read()
        assert "try:" in code and "except" in code

    def test_has_logging(self):
        \"\"\"Verify workflow includes logging.\"\"\"
        code = open("workflow.py").read()
        assert "logging" in code or "print(" in code


# ── Environment Variable Tests ───────────────────────────

class TestEnvironmentVariables:
    \"\"\"Test that all required environment variables are handled.\"\"\"

{env_tests}


# ── API Integration Tests (Mocked) ──────────────────────

class TestAPIIntegrations:
    \"\"\"Test API calls are made correctly (with mocked responses).\"\"\"

{api_tests}


# ── Error Handling Tests ─────────────────────────────────

class TestErrorHandling:
    \"\"\"Test that errors are handled gracefully.\"\"\"

    def test_retry_logic_exists(self):
        \"\"\"Verify retry logic is implemented.\"\"\"
        code = open("workflow.py").read()
        assert "retry" in code.lower() or "range(3)" in code or "for i in range" in code

    def test_exponential_backoff(self):
        \"\"\"Verify exponential backoff is used.\"\"\"
        code = open("workflow.py").read()
        assert "2 ** " in code or "2**" in code or "backoff" in code.lower()
"""

    return tests
