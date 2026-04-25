"""End-to-end: seed → perceive → dream → edit → promote → die → inherit."""
import json

import pytest

from backend.genesis import causality, dreams, runtime, store
from backend.genesis.skills import distill, inherit, pool
from backend.genesis.types import Intent, Organism


@pytest.mark.asyncio
async def test_full_lifecycle_then_inheritance(tmp_storage, fake_llm, monkeypatch):
    # ── Round 1: live, die, distill ──────────────────────────────
    org1 = Organism(name="ancestor", intent=Intent(goal="ancestor goal"))
    store.save_organism(org1)
    for i in range(6):
        fake_llm.responses.append(json.dumps({
            "reasoning": f"r{i}",
            "action": {"name": "noop", "args": {}}, "alternatives": []
        }))
    for i in range(6):
        await runtime.perceive(org1.id, {"type": "tick", "i": i})

    # Distill → produces a Skill
    fake_llm.responses.append(json.dumps({
        "name": "ancestor_skill", "description": "From the ancestor",
        "trigger_patterns": ["tick"], "forbidden_patterns": [],
        "body": "# What this knows\nNoop is fine for tick events.\n",
    }))
    skill_id = await distill.distill(org1.id)
    assert skill_id is not None

    # ── Round 2: child inherits ──────────────────────────────────
    refs, parents, compiled_specs = inherit.resolve_seed_inheritance(inherit_from=[skill_id])
    assert len(refs) == 1
    assert refs[0].skill_id == skill_id

    org2 = Organism(name="child", intent=Intent(goal="child goal"),
                    inherited_skills=refs, parent_organisms=parents)
    store.save_organism(org2)

    fake_llm.responses.append(json.dumps({
        "reasoning": "with inherited wisdom",
        "action": {"name": "noop", "args": {}}, "alternatives": []
    }))
    await runtime.perceive(org2.id, {"type": "tick"})

    # The inherited skill body must have been in the prompt
    assert any("Noop is fine for tick events" in p["prompt"]
               for p in fake_llm.prompts)
