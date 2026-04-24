"""Seed → 5 perceives → kill → assert skill exists with right frontmatter."""
import json

import pytest

from backend.genesis import runtime, store
from backend.genesis.skills import distill, pool
from backend.genesis.types import Intent, Organism


@pytest.mark.asyncio
async def test_lifecycle_produces_skill(tmp_storage, fake_llm):
    org = Organism(name="lifecycle_test", intent=Intent(goal="test goal"))
    store.save_organism(org)

    for i in range(5):
        fake_llm.responses.append(json.dumps({
            "reasoning": f"reasoning {i}",
            "action": {"name": "noop", "args": {}},
            "alternatives": [],
        }))
    for i in range(5):
        await runtime.perceive(org.id, {"type": "tick", "i": i})

    fake_llm.responses.append(json.dumps({
        "name": "lifecycle_test_skill",
        "description": "Skill distilled from lifecycle test",
        "trigger_patterns": ["tick events"],
        "forbidden_patterns": [],
        "body": "# What this knows\nNoop is fine for ticks.\n",
    }))

    skill_id = await distill.distill(org.id)
    assert skill_id is not None
    s = pool.load(skill_id)
    assert s is not None
    assert s.parent_organisms == [org.id]
    assert s.n_decisions_distilled == 5
    assert s.generation == 1


@pytest.mark.asyncio
async def test_lifecycle_skips_distillation_below_threshold(tmp_storage, fake_llm):
    org = Organism(name="too_short", intent=Intent(goal="x"))
    store.save_organism(org)
    for i in range(3):
        fake_llm.responses.append(json.dumps({
            "reasoning": "r", "action": {"name": "noop", "args": {}}, "alternatives": []
        }))
        await runtime.perceive(org.id, {"type": "tick"})

    skill_id = await distill.distill(org.id)
    assert skill_id is None
