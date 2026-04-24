"""Inherited skill body must reach the LLM prompt."""
import json
from datetime import datetime

import pytest

from backend.genesis import runtime, store
from backend.genesis.skills import pool
from backend.genesis.types import Intent, Organism, SkillRef


@pytest.mark.asyncio
async def test_inherited_skill_text_appears_in_llm_prompt(tmp_storage, fake_llm):
    skill = pool.Skill(
        skill_id="sk_inherit01", name="vip_handling",
        description="Recognize VIPs",
        distilled_at=datetime.utcnow(),
        parent_organisms=[], parent_skills=[],
        generation=1, fitness_at_death=0.9, n_decisions_distilled=20,
        trigger_patterns=[], forbidden_patterns=[],
        body="# What this knows\nVIP customers come from @bigcorp.com.",
    )
    pool.write(skill)

    org = Organism(
        intent=Intent(goal="g"),
        inherited_skills=[SkillRef(skill_id="sk_inherit01", name="vip_handling",
                                    inherited_at=datetime.utcnow())],
    )
    store.save_organism(org)

    fake_llm.responses.append(json.dumps({
        "reasoning": "ok", "action": {"name": "noop", "args": {}}, "alternatives": []
    }))

    await runtime.perceive(org.id, {"type": "x"})

    assert any("VIP customers come from @bigcorp.com" in p["prompt"]
               for p in fake_llm.prompts), "skill body missing from LLM prompt"
    assert any("vip_handling" in p["prompt"] for p in fake_llm.prompts)
