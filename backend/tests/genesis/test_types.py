"""Verify the new Phase 1 fields exist on Organism with correct defaults."""
from datetime import datetime

from backend.genesis.types import (
    Intent, MCPServerSpec, Organism, SkillRef,
)


def test_mcp_server_spec_defaults():
    s = MCPServerSpec(name="fs", command="npx")
    assert s.args == []
    assert s.env == {}
    assert s.transport == "stdio"


def test_skill_ref_required_fields():
    s = SkillRef(skill_id="sk_abc", name="example",
                 inherited_at=datetime.utcnow())
    assert s.skill_id == "sk_abc"


def test_organism_phase1_fields_default():
    o = Organism(intent=Intent(goal="test"))
    assert o.mcp_servers == []
    assert o.inherited_skills == []
    assert o.parent_organisms == []
    assert o.fitness_score == 0.0
    assert o.distilled_skill_id is None
