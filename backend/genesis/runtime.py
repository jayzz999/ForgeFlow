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
    "send_slack": (_tool_send_slack, "Post a message to a Slack channel. Args: channel (str), text (str)."),
    "http_request": (_tool_http_request,
                     "Make an HTTP request. Args: method (str), url (str), headers (dict, optional), body (dict, optional)."),
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
"""


def _build_prompt(
    org: Organism,
    perception: dict,
    recent_memory: list[Decision],
    relevant_dreams: list[Decision],
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
    try:
        return await fn(**args)
    except TypeError as e:
        return {"ok": False, "error": f"bad args for {name}: {e}"}


# ── Public: a single perception → decision cycle ───────────────────────

async def perceive(
    organism_id: str,
    perception: dict,
    *,
    is_dream: bool = False,
    shadow_branch: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    event_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
) -> Decision:
    """Process one perception event. Reason → act → record.

    Returns the resulting Decision (which has been persisted).
    """
    org = store.load_organism(organism_id)
    if not org:
        raise ValueError(f"organism {organism_id} not found")

    # Snapshot context the LLM saw (for replay/edit)
    real_history = [
        d for d in store.all_decisions(organism_id, include_dreams=False, include_shadows=False)
    ][-8:]  # last 8 real decisions

    # Naive dream relevance: LLM can compare; for now just take last 5 dreams
    dream_history = [
        d for d in store.all_decisions(organism_id, include_dreams=True, include_shadows=False)
        if d.is_dream
    ][-5:]

    if not is_dream and event_callback:
        await event_callback("organism.perceiving", {"organism_id": organism_id, "perception": perception})

    # Update state
    if not is_dream:
        org.state = OrganismState.ACTING
        store.save_organism(org)

    prompt = _build_prompt(org, perception, real_history, dream_history)

    # The actual LLM call — temperature small but nonzero so dreams diverge naturally
    raw = await generate_text(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=org.reasoning_model,
        temperature=0.4 if is_dream else 0.1,
        max_tokens=2000,
    )
    parsed = _parse_llm_json(raw)

    reasoning = str(parsed.get("reasoning", ""))[:4000]
    action = parsed.get("action") or {"name": "noop", "args": {}}
    alternatives = parsed.get("alternatives") or []
    action_name = str(action.get("name", "noop"))
    action_args = action.get("args") or {}

    if event_callback and not is_dream:
        await event_callback("organism.reasoning", {
            "organism_id": organism_id,
            "reasoning": reasoning,
            "intended_action": {"name": action_name, "args": action_args},
        })

    # Execute (skip real side effects when dreaming)
    if is_dream:
        result = {"ok": True, "simulated": True, "would_have": {"name": action_name, "args": action_args}}
    else:
        result = await _execute_tool(action_name, action_args, org)

    # Persist
    decision = Decision(
        organism_id=organism_id,
        parent_ids=parent_ids or ([real_history[-1].id] if real_history else []),
        trigger=perception,
        context_snapshot={
            "recent_memory_ids": [d.id for d in real_history],
            "dream_ids": [d.id for d in dream_history],
            "patterns_count": len(org.learned_patterns),
        },
        reasoning=reasoning,
        action={"name": action_name, "args": action_args},
        result=result,
        alternatives_considered=alternatives,
        is_dream=is_dream,
        shadow_branch=shadow_branch,
    )
    store.save_decision(decision)

    # Update lifecycle state
    if not is_dream:
        if action_name == "declare_done":
            org.state = OrganismState.PERCEIVING  # ready for next event; could become DYING if intent permanent
        else:
            org.state = OrganismState.PERCEIVING
        store.save_organism(org)

        if event_callback:
            await event_callback("organism.acted", {
                "organism_id": organism_id,
                "decision": decision.model_dump(mode="json"),
            })

    return decision


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
