from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.execution.sandbox import _validate_code_ast
from backend.shared import llm_client
from backend.shared.config import settings
from backend.shared.path_security import normalize_relative_path, resolve_within_directory
from backend.shared.security import verify_admin_token


def test_path_helpers_reject_escape_attempts(tmp_path):
    assert normalize_relative_path("clients/../config.py") == "config.py"

    for path in ("../secret.py", "/tmp/secret.py", "C:\\tmp\\secret.py"):
        with pytest.raises(ValueError):
            resolve_within_directory(tmp_path, path)


def test_admin_token_required_by_default(monkeypatch):
    monkeypatch.setattr(settings, "FORGEFLOW_ALLOW_UNAUTH_DANGEROUS", False)
    monkeypatch.setattr(settings, "FORGEFLOW_ADMIN_TOKEN", "")

    with pytest.raises(HTTPException) as exc:
        verify_admin_token(None, "run generated workflows")

    assert exc.value.status_code == 403

    monkeypatch.setattr(settings, "FORGEFLOW_ADMIN_TOKEN", "secret")
    with pytest.raises(HTTPException):
        verify_admin_token("wrong", "run generated workflows")

    verify_admin_token("secret", "run generated workflows")


def test_ast_fallback_does_not_report_execution_success():
    result = _validate_code_ast(
        "import asyncio\n\nasync def main():\n    return {'ok': True}\n"
        "\nif __name__ == '__main__':\n    asyncio.run(main())\n"
    )

    assert result.success is False
    assert result.error == "SANDBOX_UNAVAILABLE"
    assert "VALIDATION ONLY" in result.stdout


def test_workflow_run_env_excludes_llm_keys(monkeypatch):
    from backend.main import _workflow_run_env

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    monkeypatch.setenv("TARGET_URL", "https://example.com")

    env = _workflow_run_env()

    assert env["SLACK_BOT_TOKEN"] == "xoxb-test"
    assert env["TARGET_URL"] == "https://example.com"
    assert "GROQ_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env


@pytest.mark.asyncio
async def test_tool_loop_records_only_successful_safe_written_files(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    class FakeModels:
        def __init__(self):
            self.calls = 0

        async def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                part = SimpleNamespace(
                    function_call=SimpleNamespace(
                        name="write_file",
                        args={"path": "../outside.py", "content": "bad"},
                    ),
                    text=None,
                )
            elif self.calls == 2:
                part = SimpleNamespace(
                    function_call=SimpleNamespace(
                        name="write_file",
                        args={"path": "clients/../config.py", "content": "ok = True"},
                    ),
                    text=None,
                )
            else:
                part = SimpleNamespace(function_call=None, text="print('done')")
            return SimpleNamespace(
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))]
            )

    fake_client = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    monkeypatch.setattr(llm_client, "get_client", lambda: fake_client)
    monkeypatch.setattr(
        llm_client.types,
        "GenerateContentConfig",
        lambda **kwargs: kwargs,
    )

    async def fake_executor(tool_name, tool_args, project_dir):
        if tool_args["path"].startswith(".."):
            return "Error: Path must be relative and within the project directory"
        return "Written 9 chars to config.py"

    code, extra_files = await llm_client.generate_with_tools(
        prompt="p",
        system="s",
        tools_config=None,
        tool_executor=fake_executor,
    )

    assert code == "print('done')"
    assert extra_files == {"config.py": "ok = True"}
