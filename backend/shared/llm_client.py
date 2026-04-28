"""Centralized LLM client for ForgeFlow.

All LLM calls go through this module. Provides:
- generate_json() — for structured JSON responses
- generate_text() — for free-text responses
- generate_with_tools() — agentic tool-calling loop (browse, shell, write, test)
- get_client() — raw Gemini client access for the optional Gemini provider
"""

import asyncio
import json
import logging
from typing import Callable

import httpx
from google import genai
from google.genai import types

from backend.shared.config import settings

logger = logging.getLogger("forgeflow.llm")

_client: genai.Client | None = None
MAX_TOOL_ROUNDS = 15  # Safety limit for tool-calling loops
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


def get_client() -> genai.Client:
    """Get or create the singleton Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _provider() -> str:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "gemini":
        return "gemini"
    return "groq"


def _model(model: str | None, *, fast: bool = False) -> str:
    return _model_for(_provider(), model, fast=fast)


def _model_for(provider: str, model: str | None, *, fast: bool = False) -> str:
    if provider == "gemini":
        if model and not model.startswith("gemini"):
            model = None
        return model or (settings.GEMINI_FAST_MODEL if fast else settings.GEMINI_MODEL)
    if model and model.startswith("gemini"):
        model = None
    return model or (settings.GROQ_FAST_MODEL if fast else settings.GROQ_MODEL)


def _should_fallback_from_groq(exc: Exception) -> bool:
    if settings.LLM_FALLBACK_PROVIDER != "gemini" or not settings.GEMINI_API_KEY:
        return False
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    return exc.response.status_code in {408, 409, 429, 500, 502, 503, 504}


def _retry_delay(exc: httpx.HTTPStatusError, attempt: int) -> float:
    retry_after = exc.response.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), 8.0)
        except ValueError:
            pass
    return min(settings.GROQ_RETRY_BASE_SECONDS * (2 ** attempt), 8.0)


async def _groq_chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 8000,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
) -> dict:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")

    payload = {
        "model": model or settings.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(settings.GROQ_MAX_RETRIES + 1):
            response = await client.post(
                GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            try:
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code in {408, 409, 429, 500, 502, 503, 504}
                if not retryable or attempt >= settings.GROQ_MAX_RETRIES:
                    raise
                delay = _retry_delay(exc, attempt)
                logger.warning(
                    "Groq request failed with HTTP %s; retrying in %.1fs",
                    exc.response.status_code,
                    delay,
                )
                await asyncio.sleep(delay)

    raise RuntimeError("Groq request failed without a response")


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


async def generate_json(
    prompt: str,
    system: str,
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 2000,
) -> dict:
    """Call the configured LLM and return parsed JSON."""
    if _provider() == "groq":
        try:
            response = await _groq_chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt + "\n\nReturn only valid JSON."},
                ],
                model=_model_for("groq", model, fast=True),
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            if _should_fallback_from_groq(exc):
                logger.warning("Groq JSON generation failed; falling back to Gemini")
                return await _generate_json_gemini(prompt, system, model, temperature, max_tokens)
            raise
        text = response["choices"][0]["message"].get("content") or "{}"
        try:
            return _extract_json(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Groq JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}")
            return {}

    return await _generate_json_gemini(prompt, system, model, temperature, max_tokens)


async def _generate_json_gemini(
    prompt: str,
    system: str,
    model: str | None,
    temperature: float,
    max_tokens: int,
) -> dict:
    client = get_client()
    response = await client.aio.models.generate_content(
        model=_model_for("gemini", model),
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
    system: str = "",
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 8000,
) -> str:
    """Call the configured LLM and return plain text."""
    if _provider() == "groq":
        try:
            response = await _groq_chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model=_model_for("groq", model),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            if _should_fallback_from_groq(exc):
                logger.warning("Groq text generation failed; falling back to Gemini")
                return await _generate_text_gemini(prompt, system, model, temperature, max_tokens)
            raise
        return response["choices"][0]["message"].get("content") or ""

    return await _generate_text_gemini(prompt, system, model, temperature, max_tokens)


async def _generate_text_gemini(
    prompt: str,
    system: str,
    model: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    client = get_client()
    response = await client.aio.models.generate_content(
        model=_model_for("gemini", model),
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
        tools_config: Gemini Tool with function declarations when provider=gemini
        tool_executor: async fn(tool_name, tool_args, project_dir) -> str
        project_dir: Working directory for file/shell tools
        model: provider model override
        temperature: LLM temperature
        max_tokens: Max output tokens per round
        on_tool_call: Optional callback(tool_name, tool_args, result) for UI events

    Returns:
        (final_text, extra_files) where extra_files is a dict of
        {relative_path: content} for any files written via write_file tool.
    """
    if _provider() == "groq":
        try:
            return await _generate_with_tools_groq(
                prompt=prompt,
                system=system,
                tool_executor=tool_executor,
                project_dir=project_dir,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                on_tool_call=on_tool_call,
            )
        except Exception as exc:
            if _should_fallback_from_groq(exc) and tools_config is not None:
                logger.warning("Groq tool generation failed; falling back to Gemini")
            else:
                raise

    client = get_client()
    extra_files: dict[str, str] = {}

    # Build initial contents
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(f"[Agent] Round {round_num + 1}/{MAX_TOOL_ROUNDS}")

        response = await client.aio.models.generate_content(
            model=_model_for("gemini", model),
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

            # Track written files — normalize and reject path-traversal attempts
            if tool_name == "write_file" and tool_args.get("path") and not result.lower().startswith("error"):
                from backend.shared.path_security import normalize_relative_path
                try:
                    safe_path = normalize_relative_path(tool_args["path"])
                    extra_files[safe_path] = tool_args.get("content", "")
                except ValueError:
                    logger.warning(f"[Agent] Rejected unsafe write_file path: {tool_args['path']!r}")

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


def _groq_tool_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "fetch_web_page",
                "description": "Fetch a web page and return useful text content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "extract_code": {"type": "boolean"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_shell",
                "description": "Execute a safe shell command in the workflow project directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a relative file path in the workflow project directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a relative file path from the workflow project directory.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "test_api_endpoint",
                "description": "Make an HTTP request to test an API endpoint.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string"},
                        "url": {"type": "string"},
                        "headers": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["method", "url"],
                },
            },
        },
    ]


async def _generate_with_tools_groq(
    *,
    prompt: str,
    system: str,
    tool_executor: Callable,
    project_dir: str,
    model: str | None,
    temperature: float,
    max_tokens: int,
    on_tool_call: Callable | None,
) -> tuple[str, dict[str, str]]:
    extra_files: dict[str, str] = {}
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    response: dict | None = None

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(f"[Agent] Groq round {round_num + 1}/{MAX_TOOL_ROUNDS}")
        response = await _groq_chat(
            messages,
            model=_model_for("groq", model),
            temperature=temperature,
            max_tokens=max_tokens,
            tools=_groq_tool_schema(),
        )
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content") or "", extra_files

        messages.append({
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            fn = call.get("function", {})
            tool_name = fn.get("name", "")
            try:
                tool_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            result = await tool_executor(tool_name, tool_args, project_dir)

            if tool_name == "write_file" and tool_args.get("path") and not result.lower().startswith("error"):
                from backend.shared.path_security import normalize_relative_path
                try:
                    safe_path = normalize_relative_path(tool_args["path"])
                    extra_files[safe_path] = tool_args.get("content", "")
                except ValueError:
                    logger.warning(f"[Agent] Rejected unsafe write_file path: {tool_args['path']!r}")

            if on_tool_call:
                try:
                    await on_tool_call(tool_name, tool_args, result)
                except Exception:
                    pass

            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": result[:6000],
            })

    logger.warning(f"[Agent] Hit max {MAX_TOOL_ROUNDS} Groq tool rounds")
    if response:
        return response["choices"][0]["message"].get("content") or "", extra_files
    return "", extra_files
