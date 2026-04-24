"""Lock in pre-refactor behavior of runtime.perceive(). After Task 4
refactors perceive() into a 5-stage pipeline, this test must still pass."""
import json

import pytest

from backend.genesis import runtime, store
from backend.genesis.types import Intent, Organism


@pytest.mark.asyncio
async def test_perceive_produces_decision_with_expected_shape(tmp_storage, fake_llm):
    # Arrange
    org = Organism(name="t", intent=Intent(goal="test goal"))
    store.save_organism(org)

    fake_llm.responses.append(json.dumps({
        "reasoning": "I should noop",
        "action": {"name": "noop", "args": {}},
        "alternatives": [],
    }))

    # Act
    decision = await runtime.perceive(org.id, {"type": "test_event"})

    # Assert structural invariants the refactor must preserve
    assert decision.organism_id == org.id
    assert decision.trigger == {"type": "test_event"}
    assert decision.reasoning == "I should noop"
    assert decision.action == {"name": "noop", "args": {}}
    assert decision.is_dream is False
    assert decision.shadow_branch is None
    # Decision was persisted
    assert store.load_decision(org.id, decision.id) is not None


@pytest.mark.asyncio
async def test_perceive_dream_mode_skips_real_side_effects(tmp_storage, fake_llm):
    org = Organism(name="t", intent=Intent(goal="test"))
    store.save_organism(org)
    fake_llm.responses.append(json.dumps({
        "reasoning": "imagined",
        "action": {"name": "send_slack", "args": {"channel": "#x", "text": "hi"}},
        "alternatives": [],
    }))

    decision = await runtime.perceive(org.id, {"type": "imagined"}, is_dream=True)

    assert decision.is_dream is True
    # In dream mode, the action is recorded but the side effect must be simulated
    assert decision.action["name"] == "send_slack"
