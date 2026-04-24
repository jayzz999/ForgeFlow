"""5-stage perception pipeline. Phase 1 substrate.

External contract: pipeline.run(...) is called by runtime.perceive() and
returns a fully-populated Decision identical to what the old monolithic
perceive() returned. Each stage is pure-ish (no global state mutation
beyond store calls and event emission).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .. import store
from ..types import Decision, Organism

logger = logging.getLogger("genesis.pipeline")

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]


@dataclass
class PipelineContext:
    """Carried through every stage. Mutable on purpose — stages append to it."""
    organism_id: str
    perception: dict
    is_dream: bool = False
    shadow_branch: Optional[str] = None
    parent_ids: Optional[list[str]] = None
    event_callback: EventCallback = None
    # Populated by stages
    organism: Optional[Organism] = None
    real_history: list[Decision] = field(default_factory=list)
    dream_history: list[Decision] = field(default_factory=list)
    skills_text: str = ""
    tool_catalog: list[dict] = field(default_factory=list)
    llm_raw: str = ""
    parsed: dict = field(default_factory=dict)
    decision: Optional[Decision] = None


async def gather_context(ctx: PipelineContext) -> None:
    ctx.organism = store.load_organism(ctx.organism_id)
    if not ctx.organism:
        raise ValueError(f"organism {ctx.organism_id} not found")
    all_decisions = store.all_decisions(ctx.organism_id)
    ctx.real_history = [d for d in all_decisions if not d.is_dream and not d.shadow_branch][-8:]
    ctx.dream_history = [d for d in all_decisions if d.is_dream][-5:]
    from ..skills import inherit
    ctx.skills_text = inherit.load_skills_text(ctx.organism)


async def load_capabilities(ctx: PipelineContext) -> None:
    from .. import runtime
    from ..mcp import client as mcp_client
    catalog = runtime._builtin_tool_catalog()
    if ctx.organism and ctx.organism.mcp_servers:
        await mcp_client.pool.ensure_organism(ctx.organism.id, ctx.organism.mcp_servers)
    mcp_tools = await mcp_client.pool.list_tools(ctx.organism_id) if ctx.organism else []
    builtin_names = {t["name"] for t in catalog}
    catalog.extend(t for t in mcp_tools if t["name"] not in builtin_names)
    ctx.tool_catalog = catalog


async def reason(ctx: PipelineContext) -> None:
    from .. import runtime
    ctx.llm_raw = await runtime._reason_with_llm(ctx)


async def act(ctx: PipelineContext) -> None:
    from .. import runtime
    ctx.parsed = runtime._parse_llm_response(ctx.llm_raw)
    ctx.decision = await runtime._execute_action(ctx)


async def record(ctx: PipelineContext) -> None:
    from .. import runtime
    await runtime._persist_and_emit(ctx)


async def run(
    organism_id: str,
    perception: dict,
    *,
    is_dream: bool = False,
    shadow_branch: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    event_callback: EventCallback = None,
) -> Decision:
    ctx = PipelineContext(
        organism_id=organism_id,
        perception=perception,
        is_dream=is_dream,
        shadow_branch=shadow_branch,
        parent_ids=parent_ids,
        event_callback=event_callback,
    )
    await gather_context(ctx)
    await load_capabilities(ctx)
    await reason(ctx)
    await act(ctx)
    await record(ctx)
    assert ctx.decision is not None
    return ctx.decision
