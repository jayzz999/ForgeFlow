"""Pool I/O round-trip + atomic-write behavior."""
from datetime import datetime

import pytest

from backend.genesis.skills import pool


def test_write_then_load_roundtrip(tmp_storage):
    skill = pool.Skill(
        skill_id="sk_test01",
        name="test_skill",
        description="A test",
        distilled_at=datetime(2026, 1, 1, 12, 0, 0),
        parent_organisms=["o_a", "o_b"],
        parent_skills=["sk_x"],
        generation=2,
        fitness_at_death=0.5,
        n_decisions_distilled=10,
        trigger_patterns=["pattern_a"],
        forbidden_patterns=["never X"],
        body="# What this knows\nTest body content.\n",
    )
    pool.write(skill)
    loaded = pool.load("sk_test01")
    assert loaded == skill


def test_list_returns_summaries_without_body(tmp_storage):
    s = pool.Skill(skill_id="sk_listtest", name="x", description="d",
                   distilled_at=datetime.utcnow(), parent_organisms=[],
                   parent_skills=[], generation=1, fitness_at_death=0.0,
                   n_decisions_distilled=1, trigger_patterns=[],
                   forbidden_patterns=[], body="big body" * 1000)
    pool.write(s)
    summaries = pool.list_summaries()
    assert len(summaries) == 1
    assert summaries[0]["skill_id"] == "sk_listtest"
    assert "body" not in summaries[0]


def test_load_missing_returns_none(tmp_storage):
    assert pool.load("sk_missing") is None
