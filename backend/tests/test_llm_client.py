import json

import pytest

from backend.shared import llm_client
from backend.shared.config import settings


@pytest.mark.asyncio
async def test_groq_generate_json_uses_json_response_format(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FAST_MODEL", "llama-3.1-8b-instant")

    async def fake_groq_chat(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": '{"ok": true, "count": 2}'}}]}

    monkeypatch.setattr(llm_client, "_groq_chat", fake_groq_chat)

    result = await llm_client.generate_json("Return status", "You return JSON")

    assert result == {"ok": True, "count": 2}
    assert calls[0]["model"] == "llama-3.1-8b-instant"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_groq_generate_text_returns_message_content(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")

    async def fake_groq_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "Workflow ready"}}]}

    monkeypatch.setattr(llm_client, "_groq_chat", fake_groq_chat)

    result = await llm_client.generate_text("Build a workflow", "Be concise")

    assert result == "Workflow ready"


@pytest.mark.asyncio
async def test_groq_tool_loop_records_written_files(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "src/workflow.py", "content": "print('ok')"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "Done", "tool_calls": []}}]},
    ]

    async def fake_groq_chat(messages, **kwargs):
        return responses.pop(0)

    async def fake_executor(tool_name, tool_args, project_dir):
        assert tool_name == "write_file"
        assert project_dir == str(tmp_path)
        return "Written 11 chars to src/workflow.py"

    monkeypatch.setattr(llm_client, "_groq_chat", fake_groq_chat)

    code, extra_files = await llm_client.generate_with_tools(
        prompt="p",
        system="s",
        tools_config=None,
        tool_executor=fake_executor,
        project_dir=str(tmp_path),
    )

    assert code == "Done"
    assert extra_files == {"src/workflow.py": "print('ok')"}


@pytest.mark.asyncio
async def test_groq_invalid_json_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")

    async def fake_groq_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "not json"}}]}

    monkeypatch.setattr(llm_client, "_groq_chat", fake_groq_chat)

    assert await llm_client.generate_json("p", "s") == {}
