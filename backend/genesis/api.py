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
    org = runtime.seed(
        intent_goal=req.goal,
        name=req.name,
        constraints=req.constraints,
        forbidden=req.forbidden,
        success_signals=req.success_signals,
    )
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
    base = Path(store._BASE) / organism_id  # noqa: SLF001 — internal but stable
    if base.exists():
        shutil.rmtree(base)
    await events.emit("organism.died", {
        "organism_id": organism_id, "patterns_donated": org.learned_patterns,
    })
    return {"died": organism_id, "patterns_donated": org.learned_patterns}


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
