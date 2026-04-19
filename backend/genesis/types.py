"""Core data types for digital organisms.

The whole system revolves around these. Everything else is plumbing.

Key insight: there is NO `Workflow` type. There is only `Organism` (a living
thing with intent + memory + body) and `Decision` (an event in its causal
history). Workflows don't exist in Genesis — they were never the right
abstraction.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Lifecycle ──────────────────────────────────────────────────────────

class OrganismState(str, Enum):
    SEEDED = "seeded"        # Intent received, hasn't perceived anything yet
    PERCEIVING = "perceiving"  # Watching for events, idle in between
    ACTING = "acting"          # Currently reasoning + executing
    DREAMING = "dreaming"      # Imagining hypothetical futures
    DYING = "dying"            # Intent satisfied or revoked
    DEAD = "dead"              # DNA donated to gene pool


# ── Intent ─────────────────────────────────────────────────────────────

class Intent(BaseModel):
    """The mind of the organism. Immutable goal, always interpreted."""
    goal: str = Field(..., description="Natural-language statement of purpose.")
    constraints: list[str] = Field(default_factory=list, description="Hard rules.")
    success_signals: list[str] = Field(
        default_factory=list,
        description="Implicit telemetry that means we're doing well."
    )
    forbidden: list[str] = Field(default_factory=list, description="Hard rules of what NOT to do.")
    edited_at: datetime = Field(default_factory=datetime.utcnow)


# ── Decision (the atom of causality) ───────────────────────────────────

class Decision(BaseModel):
    """A single moment of organism reasoning. Atom of causal history.

    Every decision answers: 'given what I knew, what did I choose to do, and why?'
    Decisions form a directed graph (parent_ids → this) capturing causality.
    Edits to past decisions propagate via the graph.
    """
    id: str = Field(default_factory=lambda: f"d_{uuid4().hex[:12]}")
    organism_id: str
    parent_ids: list[str] = Field(
        default_factory=list,
        description="Causally upstream decisions whose outputs this depends on."
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # What the organism perceived (input)
    trigger: dict = Field(default_factory=dict, description="Event that prompted this decision.")
    context_snapshot: dict = Field(
        default_factory=dict,
        description="What the organism knew at decision time (for replay)."
    )

    # What it reasoned (LLM output)
    reasoning: str = Field("", description="Natural-language justification from the LLM.")

    # What it did (action)
    action: dict = Field(
        default_factory=dict,
        description="Tool/function invoked: {name, args}. Empty if pure reasoning."
    )
    result: dict = Field(default_factory=dict, description="Action outcome.")

    # Counterfactual material
    alternatives_considered: list[dict] = Field(
        default_factory=list,
        description="Other actions the LLM weighed but didn't choose. Used for what-ifs."
    )

    # Provenance
    is_dream: bool = Field(False, description="True if this happened in imagination, not reality.")
    edited: bool = Field(False, description="True if a user retroactively edited this.")
    edited_from: Optional[str] = Field(None, description="If edited, the original decision id.")
    shadow_branch: Optional[str] = Field(
        None,
        description="If part of a counterfactual timeline, the branch name."
    )


# ── Organism ───────────────────────────────────────────────────────────

class Organism(BaseModel):
    """A living digital entity. Has intent, memory, body, state.

    The organism IS its causal graph + intent + state. There is no compiled
    program — the runtime interprets the intent against new perceptions
    every time, using the causal graph as memory.
    """
    id: str = Field(default_factory=lambda: f"o_{uuid4().hex[:12]}")
    name: str = "unnamed"
    intent: Intent
    state: OrganismState = OrganismState.SEEDED
    born_at: datetime = Field(default_factory=datetime.utcnow)

    # Body — currently always 'interpreted'. Future: 'lora' | 'wasm' | 'native'.
    body_substrate: str = "interpreted"

    # Sensors — what the organism is watching. Stub for now.
    perception_sources: list[dict] = Field(default_factory=list)

    # Learned patterns distilled from experience (real + dreamt).
    # Each pattern is a natural-language summary the LLM can read.
    learned_patterns: list[str] = Field(default_factory=list)

    # Configurable runtime knobs
    dream_budget_per_cycle: int = 5  # how many speculative branches per idle tick
    reasoning_model: str = "gemini-2.5-flash"  # cheap; swap to sonnet for serious orgs


# ── Counterfactual Branch ──────────────────────────────────────────────

class CounterfactualBranch(BaseModel):
    """A shadow timeline created by editing a past decision.

    The branch contains the edited decision plus speculative re-executions
    of all causally downstream decisions. The user can then PROMOTE the
    branch to reality (replacing the canonical timeline from the edit point).
    """
    id: str = Field(default_factory=lambda: f"b_{uuid4().hex[:12]}")
    organism_id: str
    edited_decision_id: str
    edited_decision: Decision
    downstream_replays: list[Decision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str = ""  # LLM-written summary of how this timeline differs

    promoted: bool = False  # True if user promoted this to canonical reality
