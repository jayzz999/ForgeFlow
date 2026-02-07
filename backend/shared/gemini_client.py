"""Centralized Gemini API client for ForgeFlow.

All LLM calls go through this module. Provides:
- generate_json() — for structured JSON responses
- generate_text() — for free-text responses
- generate_with_tools() — agentic tool-calling loop (browse, shell, write, test)
- get_client() — raw Gemini client access
"""

import json
import logging
from typing import Any, Callable, Coroutine

from google import genai
from google.genai import types

from backend.shared.config import settings

logger = logging.getLogger("forgeflow.gemini")

_client: genai.Client | None = None

MAX_TOOL_ROUNDS = 15  # Safety limit for tool-calling loops


def get_client() -> genai.Client:
    """Get or create the singleton Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


async def generate_json(
    prompt: str,
    system: str,
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 2000,
) -> dict:
    """Call Gemini and return parsed JSON.

    Uses response_mime_type="application/json" to enforce JSON output.
    """
    client = get_client()

    response = await client.aio.models.generate_content(
        model=model or settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse Gemini JSON response: {e}")
        logger.debug(f"Raw response: {response.text[:500] if response.text else 'None'}")
        return {}


async def generate_text(
    prompt: str,
    system: str,
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 8000,
) -> str:
    """Call Gemini and return plain text."""
    client = get_client()

    response = await client.aio.models.generate_content(
        model=model or settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )

    return response.text or ""


async def generate_with_tools(
    prompt: str,
    system: str,
    tools_config: types.Tool,
    tool_executor: Callable,
    project_dir: str = "/tmp/forgeflow_project",
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 8000,
    on_tool_call: Callable | None = None,
) -> tuple[str, dict[str, str]]:
    """Agentic tool-calling loop — the heart of ForgeFlow's agent capability.

    Calls the LLM with tools. When the LLM returns tool_calls instead of
    text, we execute them, feed results back, and loop until the LLM
    returns its final text response.

    Args:
        prompt: The user/system prompt
        system: System instruction
        tools_config: Gemini Tool with function declarations
        tool_executor: async fn(tool_name, tool_args, project_dir) -> str
        project_dir: Working directory for file/shell tools
        model: Gemini model override
        temperature: LLM temperature
        max_tokens: Max output tokens per round
        on_tool_call: Optional callback(tool_name, tool_args, result) for UI events

    Returns:
        (final_text, extra_files) where extra_files is a dict of
        {relative_path: content} for any files written via write_file tool.
    """
    client = get_client()
    extra_files: dict[str, str] = {}

    # Build initial contents
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(f"[Agent] Round {round_num + 1}/{MAX_TOOL_ROUNDS}")

        response = await client.aio.models.generate_content(
            model=model or settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[tools_config],
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        # Check if response has function calls
        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            logger.warning("[Agent] No candidate in response")
            break
        if not candidate.content:
            logger.warning("[Agent] No content in candidate (finish_reason=%s)", getattr(candidate, 'finish_reason', 'unknown'))
            break
        if not candidate.content.parts:
            logger.warning("[Agent] No parts in content")
            break

        parts = candidate.content.parts

        # Collect all function calls in this response
        function_calls = [p for p in parts if p.function_call]
        text_parts = [p for p in parts if p.text]

        if not function_calls:
            # No tool calls — LLM is done, return the text
            final_text = "\n".join(p.text for p in text_parts if p.text)
            logger.info(f"[Agent] Done after {round_num + 1} rounds, {len(extra_files)} files written")
            return final_text, extra_files

        # Add the model's response (with function calls) to contents
        contents.append(candidate.content)

        # Execute each function call and collect responses
        function_response_parts = []
        for part in function_calls:
            fc = part.function_call
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            logger.info(f"[Agent] Tool call: {tool_name}({list(tool_args.keys())})")

            # Execute the tool
            result = await tool_executor(tool_name, tool_args, project_dir)

            # Track written files
            if tool_name == "write_file" and tool_args.get("path"):
                extra_files[tool_args["path"]] = tool_args.get("content", "")

            # Notify UI
            if on_tool_call:
                try:
                    await on_tool_call(tool_name, tool_args, result)
                except Exception:
                    pass

            # Build function response part
            function_response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response={"result": result[:6000]},  # Truncate for context window
                )
            )

        # Add all function responses as a single user turn
        contents.append(
            types.Content(role="user", parts=function_response_parts)
        )

    # Safety: hit max rounds
    logger.warning(f"[Agent] Hit max {MAX_TOOL_ROUNDS} tool rounds, returning last text")
    # Try to extract any text from the last response
    last_text = ""
    if response and response.candidates:
        for part in response.candidates[0].content.parts:
            if part.text:
                last_text += part.text
    return last_text, extra_files
