"""FastAPI routes for Genesis. Mount via:

    from backend.genesis.api import router as genesis_router
    app.include_router(genesis_router)

Endpoints:
  POST   /api/genesis/seed                              create organism from intent
  GET    /api/genesis/organisms                         list all organisms
  GET    /api/genesis/organisms/{id}                    one organism
  DELETE /api/genesis/organisms/{id}                    let it die
  POST   /api/genesis/organisms/{id}/perceive           feed a perception event
  POST   /api/genesis/organisms/{id}/dream              run a dreaming cycle
  GET    /api/genesis/organisms/{id}/causality          full causal graph
  POST   /api/genesis/organisms/{id}/edit/{decision_id} retroactively edit a decision
  POST   /api/genesis/organisms/{id}/branches/{bid}/promote  promote a branch
  GET    /api/genesis/organisms/{id}/branches           list counterfactual branches
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import causality, dreams, events, lifecycle, runtime, store

router = APIRouter(prefix="/api/genesis", tags=["genesis"])


# ── Request models ─────────────────────────────────────────────────────

class SeedRequest(BaseModel):
    goal: str = Field(..., description="Natural-language intent.")
    name: str = ""
    constraints: list[str] = []
    forbidden: list[str] = []
    success_signals: list[str] = []
    # Phase 1 additions
    inherit_from: list[str] = []
    inherit_from_organisms: list[str] = []
    max_inherited_skills: int = 5
    mcp_servers: list[dict] = []  # raw dicts → MCPServerSpec at construction


class PerceiveRequest(BaseModel):
    perception: dict[str, Any]


class EditRequest(BaseModel):
    new_action: dict | None = None
    new_trigger: dict | None = None
    new_reasoning: str | None = None


class DreamRequest(BaseModel):
    n: int | None = None


class PerceptionSourceRequest(BaseModel):
    kind: str  # "interval" | "http_poll" | "webhook"
    type: str = "event"
    interval_s: int = 60
    url: str | None = None
    method: str | None = "GET"
    headers: dict | None = None
    payload: dict | None = None


# ── Routes ─────────────────────────────────────────────────────────────

@router.post("/seed")
async def seed(req: SeedRequest):
    from .skills import inherit as _inherit
    from .types import MCPServerSpec

    inherited_refs, parent_orgs, compiled_mcp_specs = _inherit.resolve_seed_inheritance(
        inherit_from=req.inherit_from or None,
        inherit_from_organisms=req.inherit_from_organisms or None,
        max_inherited_skills=req.max_inherited_skills,
    )
    mcp_specs = [MCPServerSpec(**d) for d in (req.mcp_servers or [])]
    # Phase 4: Merge compiled skill MCP servers
    mcp_specs.extend(compiled_mcp_specs)

    org = runtime.seed(
        intent_goal=req.goal, name=req.name,
        constraints=req.constraints, forbidden=req.forbidden,
        success_signals=req.success_signals,
    )
    org.inherited_skills = inherited_refs
    org.parent_organisms = parent_orgs
    org.mcp_servers = mcp_specs
    store.save_organism(org)

    await events.emit("organism.seeded", {
        "organism_id": org.id,
        "organism": org.model_dump(mode="json"),
    })
    return {"organism": org.model_dump(mode="json")}


@router.get("/organisms")
async def list_organisms():
    orgs = store.list_organisms()
    return {"organisms": [o.model_dump(mode="json") for o in orgs]}


@router.get("/organisms/{organism_id}")
async def get_organism(organism_id: str):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    decisions = store.all_decisions(organism_id)
    return {
        "organism": org.model_dump(mode="json"),
        "decision_count": len(decisions),
        "real_decisions": sum(1 for d in decisions if not d.is_dream and not d.shadow_branch),
        "dream_decisions": sum(1 for d in decisions if d.is_dream),
        "shadow_decisions": sum(1 for d in decisions if d.shadow_branch),
    }


@router.delete("/organisms/{organism_id}")
async def kill_organism(organism_id: str):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")

    # Phase 1 — distill organism's life into a Skill before death
    from .skills import distill as _distill
    try:
        new_skill_id = await _distill.distill(organism_id)
    except Exception as e:
        import logging
        logging.getLogger("genesis.api").warning(
            f"distillation failed for {organism_id}: {e}"
        )
        new_skill_id = None

    base = Path(store._BASE) / organism_id  # noqa: SLF001
    if base.exists():
        shutil.rmtree(base)
    await events.emit("organism.died", {
        "organism_id": organism_id,
        "patterns_donated": org.learned_patterns,
        "distilled_skill_id": new_skill_id,
    })
    if new_skill_id:
        await events.emit("organism.distilled", {
            "organism_id": organism_id, "skill_id": new_skill_id,
        })
    return {"died": organism_id,
            "patterns_donated": org.learned_patterns,
            "distilled_skill_id": new_skill_id}


@router.post("/organisms/{organism_id}/perceive")
async def perceive(organism_id: str, req: PerceiveRequest):
    if not store.load_organism(organism_id):
        raise HTTPException(404, f"organism {organism_id} not found")
    decision = await runtime.perceive(
        organism_id, req.perception,
        event_callback=events.make_callback(),
    )
    return {"decision": decision.model_dump(mode="json")}


@router.post("/organisms/{organism_id}/dream")
async def dream(organism_id: str, req: DreamRequest):
    if not store.load_organism(organism_id):
        raise HTTPException(404, f"organism {organism_id} not found")
    perceptions = await dreams.imagine(
        organism_id, n=req.n,
        event_callback=events.make_callback(),
    )
    return {"imagined_count": len(perceptions), "perceptions": perceptions}


@router.get("/organisms/{organism_id}/causality")
async def get_causality(organism_id: str, include_dreams: bool = True,
                        include_shadows: bool = True):
    if not store.load_organism(organism_id):
        raise HTTPException(404, f"organism {organism_id} not found")
    return causality.graph_view(
        organism_id,
        include_dreams=include_dreams,
        include_shadows=include_shadows,
    )


@router.post("/organisms/{organism_id}/edit/{decision_id}")
async def edit_decision(organism_id: str, decision_id: str, req: EditRequest):
    if not store.load_organism(organism_id):
        raise HTTPException(404, f"organism {organism_id} not found")
    if not store.load_decision(organism_id, decision_id):
        raise HTTPException(404, f"decision {decision_id} not found")
    await events.emit("organism.edited", {
        "organism_id": organism_id, "decision_id": decision_id,
        "new_action": req.new_action, "new_trigger": req.new_trigger,
    })
    branch = await causality.edit_and_replay(
        organism_id, decision_id,
        new_action=req.new_action, new_trigger=req.new_trigger,
        new_reasoning=req.new_reasoning,
    )
    await events.emit("organism.branch_created", {
        "organism_id": organism_id,
        "branch": branch.model_dump(mode="json"),
    })
    return {"branch": branch.model_dump(mode="json")}


@router.post("/organisms/{organism_id}/branches/{branch_id}/promote")
async def promote_branch(organism_id: str, branch_id: str):
    if not store.load_branch(organism_id, branch_id):
        raise HTTPException(404, f"branch {branch_id} not found")
    result = await causality.promote_branch(organism_id, branch_id)
    await events.emit("organism.branch_promoted", {
        "organism_id": organism_id, "branch_id": branch_id, **result,
    })
    return result


@router.get("/lifecycle/status")
async def lifecycle_status():
    return lifecycle.status()


@router.post("/organisms/{organism_id}/sources")
async def add_perception_source(organism_id: str, req: PerceptionSourceRequest):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    src = req.model_dump(exclude_none=True)
    org.perception_sources.append(src)
    store.save_organism(org)
    # supervisor will mint webhook tokens & spawn polling on next reconcile
    return {"ok": True, "sources": org.perception_sources}


@router.delete("/organisms/{organism_id}/sources/{index}")
async def remove_perception_source(organism_id: str, index: int):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    if index < 0 or index >= len(org.perception_sources):
        raise HTTPException(404, "source index out of range")
    removed = org.perception_sources.pop(index)
    store.save_organism(org)
    return {"removed": removed, "sources": org.perception_sources}


@router.post("/webhook/{token}")
async def webhook_deliver(token: str, body: dict):
    try:
        return await lifecycle.deliver_webhook(token, body)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.get("/organisms/{organism_id}/branches")
async def list_branches(organism_id: str):
    return {
        "branches": [b.model_dump(mode="json")
                     for b in store.list_branches(organism_id)]
    }


# ── Skill Library ───────────────────────────────────────────────────────

@router.get("/skills")
async def list_skills():
    from .skills import pool as _pool
    return {"skills": _pool.list_summaries()}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    from .skills import pool as _pool
    s = _pool.load(skill_id)
    if not s:
        raise HTTPException(404, f"skill {skill_id} not found")
    return {
        "skill_id": s.skill_id, "name": s.name, "description": s.description,
        "distilled_at": s.distilled_at.isoformat(),
        "parent_organisms": s.parent_organisms, "parent_skills": s.parent_skills,
        "generation": s.generation, "fitness_at_death": s.fitness_at_death,
        "n_decisions_distilled": s.n_decisions_distilled,
        "trigger_patterns": s.trigger_patterns, "forbidden_patterns": s.forbidden_patterns,
        "body": s.body,
    }


@router.get("/skills/{skill_id}/lineage")
async def get_skill_lineage(skill_id: str):
    from .skills import pool as _pool
    seen: set[str] = set()
    frontier = [skill_id]
    nodes: list[dict] = []
    edges: list[dict] = []
    while frontier:
        sid = frontier.pop()
        if sid in seen:
            continue
        seen.add(sid)
        s = _pool.load(sid)
        if not s:
            continue
        nodes.append({"id": sid, "kind": "skill", "name": s.name,
                      "generation": s.generation,
                      "fitness_at_death": s.fitness_at_death})
        for parent in s.parent_skills:
            edges.append({"source": parent, "target": sid, "kind": "skill_parent"})
            frontier.append(parent)
        for org in s.parent_organisms:
            org_node_id = f"org:{org}"
            if org_node_id not in seen:
                seen.add(org_node_id)
                nodes.append({"id": org_node_id, "kind": "organism", "name": org})
            edges.append({"source": org_node_id, "target": sid, "kind": "distilled_from"})
    return {"nodes": nodes, "edges": edges}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from .skills import pool as _pool
    if not _pool.delete(skill_id):
        raise HTTPException(404, f"skill {skill_id} not found")
    return {"deleted": skill_id}


# ── MCP endpoints ───────────────────────────────────────────────────────

@router.post("/organisms/{organism_id}/mcp/attach")
async def attach_mcp(organism_id: str, spec: dict):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    from .types import MCPServerSpec
    parsed = MCPServerSpec(**spec)
    org.mcp_servers = [s for s in org.mcp_servers if s.name != parsed.name] + [parsed]
    store.save_organism(org)
    from .mcp import client as _mc
    await _mc.pool.ensure_organism(organism_id, [parsed])
    return {"ok": True, "mcp_servers": [s.model_dump() for s in org.mcp_servers]}


@router.delete("/organisms/{organism_id}/mcp/{server_name}")
async def detach_mcp(organism_id: str, server_name: str):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    before = len(org.mcp_servers)
    org.mcp_servers = [s for s in org.mcp_servers if s.name != server_name]
    if len(org.mcp_servers) == before:
        raise HTTPException(404, f"server {server_name} not attached")
    store.save_organism(org)
    return {"ok": True, "remaining": [s.model_dump() for s in org.mcp_servers]}


@router.get("/mcp/global")
async def mcp_global_status():
    from .mcp import client as _mc, catalog as _cat
    return {
        "configured": [s.model_dump() for s in _cat.load_global_specs()],
        "runtime": await _mc.pool.status(),
    }


@router.post("/mcp/global/reload")
async def mcp_global_reload():
    from .mcp import client as _mc, catalog as _cat
    specs = _cat.load_global_specs()
    await _mc.pool.ensure_global(specs)
    return {"reloaded": len(specs)}


# ── Phase 4: Embodiment — Compiled Skills ──────────────────────────────

@router.get("/compiled")
async def list_compiled_skills():
    """List all compiled skill MCP servers."""
    from .skills import compiler
    return {"compiled_skills": compiler.list_compiled()}


@router.post("/skills/{skill_id}/compile")
async def compile_skill(skill_id: str):
    """Compile a narrative skill into an executable MCP server."""
    from .skills import pool as _pool, compiler
    skill = _pool.load(skill_id)
    if not skill:
        raise HTTPException(404, f"skill {skill_id} not found")
    compiled_path = await compiler.compile_skill(skill)
    if not compiled_path:
        raise HTTPException(500, "compilation failed")
    return {"ok": True, "skill_id": skill_id, "compiled_path": compiled_path}


@router.get("/sandbox/status")
async def sandbox_status():
    """Get health status of all sandboxed compiled skill processes."""
    from .skills.sandbox import sandbox_manager
    return sandbox_manager.status()


@router.post("/sandbox/health-check")
async def sandbox_health_check():
    """Run health check on all sandboxed processes, auto-restart if needed."""
    from .skills.sandbox import sandbox_manager
    results = await sandbox_manager.health_check()
    return {"results": results}

