"""The Runtime — what makes an organism alive.

Every perception event triggers a fresh reasoning pass. There is no compiled
program, no DAG, no static workflow. The organism's intent + recent memory +
relevant dreams are loaded into context, and the LLM decides what to do.

Each reasoning pass produces a Decision that is appended to the causal graph.
The graph IS the organism's lived experience.

ACTION TOOLS the runtime exposes to the LLM:
  - send_slack(channel, text)        — talk to Slack
  - send_email(to, subject, body)    — talk via Gmail
  - sheet_append(values)             — write to Google Sheets
  - http_request(method, url, ...)   — talk to any API
  - remember(pattern)                — promote insight to learned_patterns
  - declare_done()                   — signal intent has been satisfied

These are intentionally a small fixed set. The runtime is the *body* — it
manifests the LLM's choices into the world. The organism reasons; the
runtime acts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Awaitable, Callable, Optional

from backend.shared.gemini_client import generate_text

from . import store
from .types import Decision, Organism, OrganismState

logger = logging.getLogger("genesis.runtime")


# ── Tool implementations ───────────────────────────────────────────────

async def _tool_send_slack(channel: str, text: str) -> dict:
    import httpx
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "skipped": True, "reason": "SLACK_BOT_TOKEN not set"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json; charset=utf-8"},
                json={"channel": channel, "text": text},
            )
            data = r.json()
            return {"ok": bool(data.get("ok")), "ts": data.get("ts"), "error": data.get("error")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def _tool_fetch_web_page(url: str) -> dict:
    try:
        from backend.tools.executor import _fetch_web_page
        content = await _fetch_web_page({"url": url})
        return {"ok": True, "content": content[:4000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def _tool_forge_mcp_server(name: str, description: str, org_id: str = "") -> dict:
    try:
        from backend.shared.gemini_client import generate_text
        from backend.shared.config import settings
        import os
        from backend.genesis import store
        from backend.genesis.types import MCPServerSpec
        from backend.genesis.mcp.client import pool
        
        prompt = f"""Write a Python MCP server using `fastmcp` (from mcp.server.fastmcp import FastMCP) based on this description:
{description}

The server name should be "{name}".
Use httpx for any API calls.
Return ONLY valid Python code without markdown fences.
"""
        code = await generate_text(prompt=prompt, system="You are an expert Python MCP server developer.", model=settings.GEMINI_MODEL, max_tokens=4000)
        
        import re
        match = re.search(r"```(?:python)?\s*(.*?)\s*```", code, re.DOTALL)
        if match:
            code = match.group(1)
        else:
            # Fallback if no markdown blocks are found but trailing text exists
            code = code.split("```")[0].strip()
            
        org = store.load_organism(org_id)
        if not org:
            return {"ok": False, "error": "Organism not found"}
            
        org_dir = store._organism_dir(org.id)
        mcps_dir = org_dir / "mcps"
        os.makedirs(mcps_dir, exist_ok=True)
        file_path = str(mcps_dir / f"{name}.py")
        
        with open(file_path, "w") as f:
            f.write(code)
        os.chmod(file_path, 0o755)
        
        # Determine the Python executable to use
        import sys
        python_exe = sys.executable
        
        spec = MCPServerSpec(name=name, command=python_exe, args=[file_path])
        org.mcp_servers.append(spec)
        store.save_organism(org)
        
        await pool.ensure_organism(org.id, [spec])
        
        return {"ok": True, "path": file_path, "message": f"MCP server '{name}' successfully created, attached to your DNA, and loaded into your available tools!"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _tool_http_request(method: str, url: str, headers: dict | None = None,
                             body: dict | None = None) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.request(method.upper(), url, headers=headers or {}, json=body)
            try:
                payload = r.json()
            except Exception:
                payload = r.text[:1500]
            return {"ok": r.is_success, "status": r.status_code, "body": payload}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Map of tool name → (callable, description for LLM prompt)
TOOLS: dict[str, tuple[Callable[..., Awaitable[dict]], str]] = {
    "send_slack": (_tool_send_slack, "Post a message to a Slack channel or User. Args: channel (str, can be channel ID like #general or User ID for DM), text (str)."),
    "http_request": (_tool_http_request,
                     "Make an HTTP request. Args: method (str), url (str), headers (dict, optional), body (dict, optional)."),
    "fetch_web_page": (_tool_fetch_web_page, "Fetch and read the text content of a web page. Args: url (str)."),
    "forge_mcp_server": (_tool_forge_mcp_server, "Autonomously write and deploy a new MCP Python server to give yourself new capabilities. Args: name (str, no spaces), description (str, detailed explanation of what APIs it connects to and what tools it should expose)."),
    "remember": (None, "Record a learned pattern. Args: pattern (str). Use sparingly — only durable insights."),
    "declare_done": (None, "Signal the intent has been satisfied for this trigger. Args: summary (str)."),
}


# ── Core reasoning step ────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the reasoning core of a living digital organism.
You do not generate code. You do not compile workflows. You decide, in this
exact moment, what to do given your intent and what you currently perceive.

You will be given:
  - INTENT: the immutable goal you exist to serve
  - CONSTRAINTS / FORBIDDEN: hard rules
  - LEARNED PATTERNS: durable insights from your past experiences (real + dreamt)
  - RECENT MEMORY: the last few decisions you made (real)
  - RELEVANT DREAMS: hypothetical scenarios you have already imagined matching this moment
  - CURRENT PERCEPTION: the new event you must respond to
  - AVAILABLE TOOLS: what you can do in the world

Respond with STRICT JSON of this shape:
{
  "reasoning": "Natural-language explanation of why you are choosing this action.",
  "action": {"name": "<tool_name>", "args": {...}},
  "alternatives": [
    {"name": "<other_tool>", "args": {...}, "why_not": "..."},
    ...
  ]
}

Rules:
  - Always include reasoning — it is what makes you legible to humans.
  - Always include 1–2 alternatives — they enable counterfactual analysis.
  - If the intent is satisfied for this perception, action.name = "declare_done".
  - If you need no action (purely observational), action.name = "noop".
  - Never invent tool names. Only use tools listed in AVAILABLE TOOLS.

CRITICAL — ANTI-REPETITION:
  - BEFORE choosing an action, carefully review RECENT MEMORY.
  - If a previous decision already used a tool AND its result was {"ok": true},
    that step is DONE. Do NOT repeat it. Move on to the NEXT step of your plan.
  - Think step-by-step: What have I already accomplished? What is the next
    logical step to fulfill my intent?
  - Your intent may require MULTIPLE steps. Execute them ONE AT A TIME, in order.
    Each perception cycle should advance to the NEXT step.
  - If you see MCP tools (prefixed mcp__) in AVAILABLE TOOLS, prefer using
    those over forge_mcp_server — the server is already running.
"""


def _build_prompt(
    org: Organism,
    perception: dict,
    recent_memory: list[Decision],
    relevant_dreams: list[Decision],
    tool_catalog: list[dict] | None = None,
) -> str:
    def _decision_brief(d: Decision) -> dict:
        return {
            "id": d.id,
            "when": d.timestamp.isoformat(),
            "trigger": d.trigger,
            "action": d.action,
            "result_ok": d.result.get("ok") if isinstance(d.result, dict) else None,
            "reasoning": d.reasoning[:300],
            "is_dream": d.is_dream,
        }

    if tool_catalog:
        builtin = [t for t in tool_catalog if not t["name"].startswith("mcp__")]
        mcp = [t for t in tool_catalog if t["name"].startswith("mcp__")]
        tool_block_lines = ["AVAILABLE TOOLS:", "=== Built-in ==="]
        for t in builtin:
            tool_block_lines.append(f"  {t['name']}: {t.get('description', '')}")
        if mcp:
            from collections import defaultdict
            by_server = defaultdict(list)
            for t in mcp:
                by_server[t.get("server", "unknown")].append(t)
            for server, ts in by_server.items():
                tool_block_lines.append(f"=== MCP: {server} ===")
                for t in ts:
                    tool_block_lines.append(f"  {t['name']}: {t.get('description', '')}")
        tools_doc = "\n".join(tool_block_lines)
    else:
        tools_doc = {name: desc for name, (_, desc) in TOOLS.items()}
        tools_doc["noop"] = "Take no action. Args: {}."

    parts = {
        "INTENT": org.intent.goal,
        "CONSTRAINTS": org.intent.constraints,
        "FORBIDDEN": org.intent.forbidden,
        "SUCCESS_SIGNALS": org.intent.success_signals,
        "LEARNED_PATTERNS": org.learned_patterns,
        "RECENT_MEMORY": [_decision_brief(d) for d in recent_memory],
        "RELEVANT_DREAMS": [_decision_brief(d) for d in relevant_dreams],
        "CURRENT_PERCEPTION": perception,
        "AVAILABLE_TOOLS": tools_doc,
    }
    return json.dumps(parts, indent=2, default=str)


def _parse_llm_json(text: str) -> dict:
    """Tolerant JSON extraction. LLMs sometimes wrap with markdown."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except Exception:
        # Last resort — find first { ... last }
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                pass
        return {"reasoning": text, "action": {"name": "noop", "args": {}}, "alternatives": []}


async def _execute_tool(name: str, args: dict, org: Organism) -> dict:
    """Manifest the LLM's chosen action in the real world."""
    if name == "noop":
        return {"ok": True, "noop": True}
    if name == "declare_done":
        return {"ok": True, "done": True, "summary": args.get("summary", "")}
    if name == "remember":
        pattern = args.get("pattern", "").strip()
        if pattern and pattern not in org.learned_patterns:
            org.learned_patterns.append(pattern)
            store.save_organism(org)
        return {"ok": True, "patterns_total": len(org.learned_patterns)}
    if name not in TOOLS:
        return {"ok": False, "error": f"unknown tool: {name}"}
    fn, _ = TOOLS[name]
    if fn is None:
        return {"ok": False, "error": f"tool {name} has no implementation"}
        
    # Inject organism ID into meta-tools that need it
    if name == "forge_mcp_server":
        args["org_id"] = org.id
        
    try:
        return await fn(**args)
    except TypeError as e:
        return {"ok": False, "error": f"bad args for {name}: {e}"}


# ── Pipeline helpers ───────────────────────────────────────────────────

def _builtin_tool_catalog() -> list[dict]:
    """Return the list of tool descriptors the LLM can choose from."""
    catalog = [{"name": name, "description": desc} for name, (_, desc) in TOOLS.items()]
    catalog.append({"name": "noop", "description": "Take no action. Args: {}."})
    return catalog


async def _reason_with_llm(ctx) -> str:
    """Build prompt from context and call the LLM. Returns raw LLM output string."""
    org = ctx.organism
    prompt = _build_prompt(org, ctx.perception, ctx.real_history, ctx.dream_history,
                           tool_catalog=getattr(ctx, "tool_catalog", None) or None)
    if ctx.skills_text:
        prompt = ctx.skills_text + "\n\n" + prompt

    if not ctx.is_dream and ctx.event_callback:
        await ctx.event_callback("organism.perceiving", {
            "organism_id": ctx.organism_id,
            "perception": ctx.perception,
        })

    # Update state to ACTING
    if not ctx.is_dream:
        org.state = OrganismState.ACTING
        store.save_organism(org)

    raw = await generate_text(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=org.reasoning_model,
        temperature=0.4 if ctx.is_dream else 0.1,
        max_tokens=2000,
    )

    parsed = _parse_llm_json(raw)
    reasoning = str(parsed.get("reasoning", ""))[:4000]
    action = parsed.get("action") or {"name": "noop", "args": {}}
    action_name = str(action.get("name", "noop"))
    action_args = action.get("args") or {}

    if ctx.event_callback and not ctx.is_dream:
        await ctx.event_callback("organism.reasoning", {
            "organism_id": ctx.organism_id,
            "reasoning": reasoning,
            "intended_action": {"name": action_name, "args": action_args},
        })

    return raw


def _parse_llm_response(raw: str) -> dict:
    """JSON-extract the LLM's raw output."""
    return _parse_llm_json(raw)


async def _synthesize_dream_result(ctx, tool_name: str) -> dict:
    """Ask the LLM to invent a plausible result for an MCP tool call in a dream."""
    raw = await generate_text(
        prompt=(f"You are simulating the result of calling MCP tool {tool_name} "
                f"with args {ctx.parsed.get('action', {}).get('args', {})}. "
                f"Return STRICT JSON: a plausible result object."),
        system="Return only JSON, no preamble.",
        temperature=0.6, max_tokens=400,
    )
    try:
        import json as _j
        return {"ok": True, "simulated": True, "content": _j.loads(raw)}
    except Exception:
        return {"ok": True, "simulated": True, "content": raw}


async def _execute_action(ctx) -> Decision:
    """Run the chosen tool (or simulate in dream mode). Constructs Decision but does NOT persist."""
    org = ctx.organism
    parsed = ctx.parsed
    real_history = ctx.real_history
    dream_history = ctx.dream_history

    reasoning = str(parsed.get("reasoning", ""))[:4000]
    action = parsed.get("action") or {"name": "noop", "args": {}}
    alternatives = parsed.get("alternatives") or []
    action_name = str(action.get("name", "noop"))
    action_args = action.get("args") or {}

    # MCP tool dispatch — early return before built-in tool execution
    tool_name = ctx.parsed.get("action", {}).get("name", "")
    if tool_name.startswith("mcp__"):
        if ctx.is_dream:
            result = await _synthesize_dream_result(ctx, tool_name)
        else:
            from .mcp import client as mcp_client
            args = ctx.parsed.get("action", {}).get("args", {})
            result = await mcp_client.pool.call(ctx.organism_id, tool_name, args,
                                                 is_dream=False)
        decision = Decision(
            organism_id=ctx.organism_id,
            parent_ids=ctx.parent_ids or ([real_history[-1].id] if real_history else []),
            trigger=ctx.perception,
            context_snapshot={
                "recent_memory_ids": [d.id for d in real_history],
                "dream_ids": [d.id for d in dream_history],
                "patterns_count": len(org.learned_patterns),
            },
            reasoning=reasoning,
            action={"name": action_name, "args": action_args},
            result=result,
            alternatives_considered=alternatives,
            is_dream=ctx.is_dream,
            shadow_branch=ctx.shadow_branch,
        )
        return decision

    # Execute (skip real side effects when dreaming)
    if ctx.is_dream:
        result = {"ok": True, "simulated": True, "would_have": {"name": action_name, "args": action_args}}
    else:
        result = await _execute_tool(action_name, action_args, org)

    decision = Decision(
        organism_id=ctx.organism_id,
        parent_ids=ctx.parent_ids or ([real_history[-1].id] if real_history else []),
        trigger=ctx.perception,
        context_snapshot={
            "recent_memory_ids": [d.id for d in real_history],
            "dream_ids": [d.id for d in dream_history],
            "patterns_count": len(org.learned_patterns),
        },
        reasoning=reasoning,
        action={"name": action_name, "args": action_args},
        result=result,
        alternatives_considered=alternatives,
        is_dream=ctx.is_dream,
        shadow_branch=ctx.shadow_branch,
    )
    return decision


async def _persist_and_emit(ctx) -> None:
    """Save decision, fire events, update organism state, compute fitness."""
    org = ctx.organism
    decision = ctx.decision

    store.save_decision(decision)

    # Update lifecycle state
    if not ctx.is_dream:
        action_name = decision.action.get("name", "noop")
        if action_name == "declare_done":
            org.state = OrganismState.PERCEIVING
        else:
            org.state = OrganismState.PERCEIVING
        store.save_organism(org)

        if ctx.event_callback:
            await ctx.event_callback("organism.acted", {
                "organism_id": ctx.organism_id,
                "decision": decision.model_dump(mode="json"),
            })

    # Compute fitness placeholder (new in Phase 1)
    if org and not ctx.is_dream:
        reals = [d for d in store.all_decisions(org.id) if not d.is_dream and not d.shadow_branch]
        ok = sum(1 for d in reals if d.result.get("ok") is True)
        org.fitness_score = ok / max(len(reals), 1)
        store.save_organism(org)


# ── Public: a single perception → decision cycle ───────────────────────

async def perceive(
    organism_id: str,
    perception: dict,
    *,
    is_dream: bool = False,
    shadow_branch: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    event_callback=None,
) -> Decision:
    """Public entrypoint. Delegates to the pipeline."""
    from .pipeline import stages
    return await stages.run(
        organism_id, perception,
        is_dream=is_dream, shadow_branch=shadow_branch,
        parent_ids=parent_ids, event_callback=event_callback,
    )


# ── Convenience: birth a new organism ──────────────────────────────────

def seed(intent_goal: str, *, name: str = "", constraints: list[str] | None = None,
         forbidden: list[str] | None = None,
         success_signals: list[str] | None = None) -> Organism:
    """Drop an intent seed into the world. An organism crystallizes."""
    from .types import Intent
    org = Organism(
        name=name or intent_goal[:40],
        intent=Intent(
            goal=intent_goal,
            constraints=constraints or [],
            forbidden=forbidden or [],
            success_signals=success_signals or [],
        ),
        state=OrganismState.PERCEIVING,
    )
    store.save_organism(org)
    logger.info(f"[Genesis] Seeded organism {org.id}: {org.name}")
    return org
