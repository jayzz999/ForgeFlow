"""Causality manipulation — the soul of the Genesis demo.

Every Decision has parent_ids. Together they form a directed graph capturing
what each decision *depended on*. This module:

  1. Builds the graph view (for UI inspection)
  2. Identifies descendants of an edited decision (causal lightcone)
  3. Creates a CounterfactualBranch that re-executes those descendants
     under the edited assumption — without touching reality
  4. Optionally PROMOTES the branch, replacing canonical history from the
     edit point forward (the moment that breaks audience brains in the demo)

The key trick: when re-executing a downstream decision in the shadow branch,
we replace its trigger/context with the edited upstream values, then call the
runtime exactly as if it were live. The LLM doesn't know it's in a
counterfactual — it just reasons against new context, which is the whole
point.
"""

from __future__ import annotations

import logging
from typing import Optional

from . import runtime, store
from .types import CounterfactualBranch, Decision

logger = logging.getLogger("genesis.causality")


# ── Graph view ─────────────────────────────────────────────────────────

def graph_view(organism_id: str, *, include_dreams: bool = True,
               include_shadows: bool = False) -> dict:
    """Return a {nodes, edges} representation suitable for the UI."""
    decisions = store.all_decisions(
        organism_id, include_dreams=include_dreams, include_shadows=include_shadows
    )
    nodes = []
    edges = []
    for d in decisions:
        nodes.append({
            "id": d.id,
            "timestamp": d.timestamp.isoformat(),
            "trigger_summary": _summarize(d.trigger),
            "action": d.action,
            "result_ok": (d.result.get("ok") if isinstance(d.result, dict) else None),
            "reasoning": d.reasoning,
            "is_dream": d.is_dream,
            "edited": d.edited,
            "shadow_branch": d.shadow_branch,
            "alternatives": d.alternatives_considered,
        })
        for pid in d.parent_ids:
            edges.append({"from": pid, "to": d.id})
    return {"nodes": nodes, "edges": edges}


def _summarize(d: dict, n: int = 80) -> str:
    s = str(d)
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Descendants (causal lightcone) ─────────────────────────────────────

def descendants(organism_id: str, decision_id: str) -> list[Decision]:
    """All decisions causally downstream of the given decision (BFS).

    A decision is downstream if it has a parent_id chain reaching decision_id.
    """
    all_d = {d.id: d for d in store.all_decisions(organism_id)}
    children: dict[str, list[str]] = {}
    for d in all_d.values():
        for p in d.parent_ids:
            children.setdefault(p, []).append(d.id)

    seen = set()
    queue = list(children.get(decision_id, []))
    out: list[Decision] = []
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        if nid in all_d:
            out.append(all_d[nid])
            queue.extend(children.get(nid, []))
    # Topological-ish: sort by timestamp
    return sorted(out, key=lambda d: d.timestamp)


# ── Edit + propagate ──────────────────────────────────────────────────

async def edit_and_replay(
    organism_id: str,
    decision_id: str,
    *,
    new_action: Optional[dict] = None,
    new_trigger: Optional[dict] = None,
    new_reasoning: Optional[str] = None,
) -> CounterfactualBranch:
    """Create a counterfactual branch by editing one past decision.

    The edit creates a new shadow Decision (marked edited) and then re-runs
    the runtime over each descendant in causal order, marking each shadow
    re-execution with the same shadow_branch id. Reality is untouched.
    """
    original = store.load_decision(organism_id, decision_id)
    if not original:
        raise ValueError(f"decision {decision_id} not found")

    # 1) Build the edited shadow version of the original decision.
    edited = Decision(
        organism_id=organism_id,
        parent_ids=original.parent_ids,
        trigger=new_trigger or original.trigger,
        context_snapshot=original.context_snapshot,
        reasoning=new_reasoning or original.reasoning,
        action=new_action or original.action,
        result={"ok": True, "edited_shadow": True, "note": "synthetic — not executed in reality"},
        alternatives_considered=original.alternatives_considered,
        is_dream=False,
        edited=True,
        edited_from=original.id,
    )
    branch = CounterfactualBranch(
        organism_id=organism_id,
        edited_decision_id=original.id,
        edited_decision=edited,
    )
    edited.shadow_branch = branch.id
    store.save_decision(edited)

    # 2) For each descendant in causal order, re-run the runtime against the
    #    *new* context. We swap parent_ids so the descendant's new shadow
    #    references the edited shadow rather than the original.
    desc = descendants(organism_id, decision_id)
    id_remap = {original.id: edited.id}  # original_id → shadow_id

    for d in desc:
        # Compute new parent ids — swap any reference to remapped originals
        new_parents = [id_remap.get(p, p) for p in d.parent_ids]

        # Re-execute by calling runtime.perceive in dream-style (no real I/O)
        # but with shadow_branch set so we can identify these later.
        shadow = await runtime.perceive(
            organism_id=organism_id,
            perception=d.trigger,
            is_dream=True,                      # don't side-effect the world
            shadow_branch=branch.id,            # but DO mark as part of branch
            parent_ids=new_parents,
        )
        # The runtime stores it as is_dream=True; flip it for branch semantics.
        # (Dreams = imagination of the future. Shadows = re-execution of the past.)
        shadow.is_dream = False
        shadow.shadow_branch = branch.id
        store.save_decision(shadow)

        id_remap[d.id] = shadow.id
        branch.downstream_replays.append(shadow)

    # 3) Have the LLM summarize how this timeline differs from canonical.
    branch.summary = await _summarize_divergence(original, edited, branch.downstream_replays)
    store.save_branch(branch)
    logger.info(
        f"[Causality] branch {branch.id} on org {organism_id}: "
        f"edited {original.id}, replayed {len(branch.downstream_replays)} descendants"
    )
    return branch


async def promote_branch(organism_id: str, branch_id: str) -> dict:
    """Promote a counterfactual branch to canonical reality.

    We don't delete the original timeline — we mark the branch's shadow
    decisions as canonical (clear shadow_branch). Original decisions remain
    in storage marked superseded so the past is auditable.
    """
    b = store.load_branch(organism_id, branch_id)
    if not b:
        raise ValueError(f"branch {branch_id} not found")

    # Mark canonical originals as superseded
    superseded_ids = [b.edited_decision_id] + [
        d.id for d in store.all_decisions(organism_id)
        if any(b.edited_decision_id in [p] for p in d.parent_ids)
    ]
    for sid in superseded_ids:
        d = store.load_decision(organism_id, sid)
        if not d:
            continue
        d.shadow_branch = f"superseded_by:{branch_id}"
        store.save_decision(d)

    # Promote shadows
    promoted = []
    for sd in [b.edited_decision] + b.downstream_replays:
        sd.shadow_branch = None  # canonical now
        store.save_decision(sd)
        promoted.append(sd.id)

    b.promoted = True
    store.save_branch(b)
    return {"promoted_decisions": promoted, "superseded_decisions": superseded_ids}


# ── LLM-written diff summary ───────────────────────────────────────────

async def _summarize_divergence(
    original: Decision, edited: Decision, replays: list[Decision]
) -> str:
    from backend.shared.gemini_client import generate_text
    import json as _json

    payload = {
        "original_decision": {"action": original.action, "reasoning": original.reasoning[:300]},
        "edited_decision": {"action": edited.action, "reasoning": edited.reasoning[:300]},
        "downstream_replays": [
            {"action": r.action, "reasoning": r.reasoning[:200]} for r in replays
        ],
    }
    prompt = (
        "Two timelines diverged from one editable past moment. "
        "In one paragraph (no headings, no markdown), summarize how the "
        "alternate timeline differs from the original — what changed, what "
        "stayed the same, and the likely real-world consequence.\n\n"
        + _json.dumps(payload, indent=2, default=str)
    )
    try:
        return (await generate_text(
            prompt=prompt,
            system="You are a precise narrator of counterfactual timelines.",
            temperature=0.2,
            max_tokens=400,
        )).strip()
    except Exception as e:
        return f"(divergence summary unavailable: {e})"
