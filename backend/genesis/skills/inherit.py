"""Resolve inheritance at seed time and load skill text at perceive time."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import pool
from ..types import Organism, SkillRef


# Token budget heuristic: ~4 chars per token. Cap at ~3000 tokens = ~12000 chars.
SKILLS_TEXT_CHAR_BUDGET = 12000


def resolve_seed_inheritance(
    *,
    inherit_from: Optional[list[str]] = None,
    inherit_from_organisms: Optional[list[str]] = None,
    max_inherited_skills: int = 5,
) -> tuple[list[SkillRef], list[str]]:
    """Returns (inherited_skills, parent_organism_ids) for the new organism."""
    skill_ids: set[str] = set(inherit_from or [])
    parent_orgs: set[str] = set()

    if inherit_from_organisms:
        from .. import store
        for oid in inherit_from_organisms:
            parent_orgs.add(oid)
            o = store.load_organism(oid)
            if o:
                for sr in o.inherited_skills:
                    skill_ids.add(sr.skill_id)
                if o.distilled_skill_id:
                    skill_ids.add(o.distilled_skill_id)

    skills = []
    for sid in skill_ids:
        s = pool.load(sid)
        if s:
            skills.append(s)
    skills.sort(key=lambda s: s.fitness_at_death, reverse=True)
    skills = skills[:max_inherited_skills]

    now = datetime.utcnow()
    refs = [SkillRef(skill_id=s.skill_id, name=s.name, inherited_at=now)
            for s in skills]

    # Phase 4: Embodiment — collect compiled skill MCP servers
    compiled_mcp_specs = []
    from . import compiler
    from ..types import MCPServerSpec
    import sys
    for s in skills:
        compiled_path = compiler.get_compiled_path(s.skill_id)
        if compiled_path:
            compiled_mcp_specs.append(MCPServerSpec(
                name=f"compiled_{s.name}",
                command=sys.executable,
                args=[compiled_path],
            ))

    return refs, sorted(parent_orgs), compiled_mcp_specs


def load_skills_text(organism: Organism) -> str:
    """Return the prompt block to inject into the LLM call.
    Empty string if the organism has no inherited skills."""
    if not organism.inherited_skills:
        return ""
    blocks: list[str] = [
        "INHERITED WISDOM (read carefully — these are skills your ancestors distilled):\n"
    ]
    used = 0
    refs_sorted = sorted(
        organism.inherited_skills,
        key=lambda r: pool.load(r.skill_id).fitness_at_death if pool.load(r.skill_id) else 0,
        reverse=True,
    )
    for ref in refs_sorted:
        s = pool.load(ref.skill_id)
        if not s:
            continue
        block = (
            f"\n=== Skill: {s.name} (gen {s.generation}, fitness {s.fitness_at_death:.2f}) ===\n"
            f"{s.body}\n"
        )
        if used + len(block) > SKILLS_TEXT_CHAR_BUDGET:
            break
        blocks.append(block)
        used += len(block)
    return "".join(blocks)
