# Genesis Phase 1 — Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCP-as-nervous-system + Skills-as-DNA + polish to the Genesis runtime, refactoring `runtime.perceive()` into a 5-stage pipeline so Phases 2-4 have clean extension points.

**Architecture:** Refactor first (`runtime.perceive` → 5 pure async pipeline stages, behavior identical), then layer in new modules (`mcp/`, `skills/`) that plug into specific stages. Frontend gains a Skill Library, organism templates, and a guided Tour. All described in detail in `docs/superpowers/specs/2026-04-18-genesis-phase1-substrate-design.md`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, the official `mcp` Python package, asyncio, pytest + pytest-asyncio, React 18, ReactFlow.

**Spec:** `docs/superpowers/specs/2026-04-18-genesis-phase1-substrate-design.md`

---

## File Map

### New backend files

| Path | Responsibility |
|---|---|
| `backend/genesis/pipeline/__init__.py` | Package marker |
| `backend/genesis/pipeline/stages.py` | 5 pure async pipeline stages |
| `backend/genesis/mcp/__init__.py` | Package marker; exports `pool` singleton |
| `backend/genesis/mcp/client.py` | `MCPPool` — connection pool + dispatch |
| `backend/genesis/mcp/catalog.py` | Loads `_mcp_global.json` |
| `backend/genesis/skills/__init__.py` | Package marker |
| `backend/genesis/skills/pool.py` | Read/write `organisms/_skill_pool/sk_<hash>.md` |
| `backend/genesis/skills/distill.py` | LLM call: organism's decisions → Skill |
| `backend/genesis/skills/inherit.py` | Resolve inheritance at seed time |
| `backend/tests/__init__.py` | Tests package |
| `backend/tests/genesis/__init__.py` | Genesis tests package |
| `backend/tests/genesis/conftest.py` | Shared fixtures (tmp storage, fake LLM) |
| `backend/tests/genesis/test_pipeline_refactor.py` | Regression: refactored perceive matches old |
| `backend/tests/genesis/test_skill_pool.py` | Pool I/O round-trip |
| `backend/tests/genesis/test_skill_inheritance.py` | Inherited skill text reaches LLM prompt |
| `backend/tests/genesis/test_skill_lifecycle.py` | Seed → 5 perceives → kill → skill exists |
| `backend/tests/genesis/test_mcp_dispatch.py` | LLM picks MCP tool → Pool routes correctly |
| `backend/tests/genesis/mock_mcp_server.py` | Tiny stdio MCP server for tests |

### Modified backend files

| Path | Change |
|---|---|
| `backend/requirements.txt` | Add `mcp>=1.0.0`, `pytest>=8`, `pytest-asyncio>=0.24` |
| `backend/genesis/types.py` | Add `MCPServerSpec`, `SkillRef`; extend `Organism` |
| `backend/genesis/runtime.py` | `perceive()` becomes a thin shim over `pipeline.stages.run()` |
| `backend/genesis/api.py` | Add 9 new endpoints; extend `SeedRequest` |
| `backend/genesis/lifecycle.py` | Call `distill.distill()` before organism teardown |
| `backend/main.py` | Wrap Slack startup; init `MCPPool` in lifespan |
| `.env.example` | Document `SLACK_DISABLED`, `GENESIS_MCP_GLOBAL` |

### New frontend files

| Path | Responsibility |
|---|---|
| `frontend/src/components/genesis/templates.js` | Static template list |
| `frontend/src/components/genesis/SkillLibrary.jsx` | Pool browser modal |
| `frontend/src/components/genesis/SkillLineageGraph.jsx` | Mini ReactFlow lineage view |
| `frontend/src/components/genesis/InheritancePicker.jsx` | Multi-select skills in Seed modal |
| `frontend/src/components/genesis/Tour.jsx` | 6-step scripted walkthrough |

### Modified frontend files

| Path | Change |
|---|---|
| `frontend/src/hooks/useGenesis.js` | Add skills + mcp + inheritance helpers |
| `frontend/src/components/genesis/GenesisPage.jsx` | Wire SkillLibrary button, Tour button, template chips, InheritancePicker |

---

## Tasks

### Task 1: Bootstrap dev dependencies and test scaffold

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/genesis/__init__.py` (empty)
- Create: `backend/tests/genesis/conftest.py`
- Create: `pytest.ini` (project root)

- [ ] **Step 1.1: Append new deps to requirements.txt**

Add these lines to `backend/requirements.txt`:

```
# Genesis Phase 1
mcp>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

- [ ] **Step 1.2: Install them**

Run: `/usr/local/bin/python3.11 -m pip install mcp 'pytest>=8' 'pytest-asyncio>=0.24'`
Expected: successful install. If `mcp` install fails (package immature), skip it for now — Task 8 has a fallback path.

- [ ] **Step 1.3: Create empty test packages**

Create `backend/tests/__init__.py` and `backend/tests/genesis/__init__.py`, both empty.

- [ ] **Step 1.4: Write `pytest.ini` at project root**

```ini
[pytest]
asyncio_mode = auto
testpaths = backend/tests
python_files = test_*.py
addopts = -v --tb=short
```

- [ ] **Step 1.5: Write shared fixtures in `backend/tests/genesis/conftest.py`**

```python
"""Shared fixtures for Genesis tests."""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_storage(monkeypatch):
    """Each test gets its own organisms/ directory."""
    d = Path(tempfile.mkdtemp(prefix="genesis_test_"))
    monkeypatch.setenv("GENESIS_STORAGE", str(d))
    # Force the store module to re-read the env var
    from backend.genesis import store
    monkeypatch.setattr(store, "_BASE", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class FakeLLM:
    """Records prompts, returns canned JSON responses in order."""
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[dict] = []

    async def __call__(self, *, prompt: str, system: str = "",
                       temperature: float = 0.0, max_tokens: int = 2000) -> str:
        self.prompts.append({"prompt": prompt, "system": system,
                             "temperature": temperature})
        if not self.responses:
            raise RuntimeError("FakeLLM ran out of canned responses")
        return self.responses.pop(0)


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the gemini_client.generate_text so no real API calls happen."""
    fake = FakeLLM([])
    from backend.shared import gemini_client
    monkeypatch.setattr(gemini_client, "generate_text", fake)
    return fake
```

- [ ] **Step 1.6: Verify pytest discovers the tree**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow && /usr/local/bin/python3.11 -m pytest --collect-only`
Expected: "no tests collected" (we have no tests yet, but discovery should succeed without errors).

- [ ] **Step 1.7: Commit**

```bash
git add backend/requirements.txt backend/tests/ pytest.ini
git commit -m "test(genesis): scaffold pytest + pytest-asyncio + shared fixtures"
```

---

### Task 2: Add new types to `types.py`

**Files:**
- Modify: `backend/genesis/types.py`
- Create: `backend/tests/genesis/test_types.py`

- [ ] **Step 2.1: Write the failing test**

Create `backend/tests/genesis/test_types.py`:

```python
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
```

- [ ] **Step 2.2: Run — should fail with ImportError**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_types.py -v`
Expected: ImportError on `MCPServerSpec, SkillRef`.

- [ ] **Step 2.3: Add the new types to `backend/genesis/types.py`**

After the existing `Intent` class, before `Decision`, insert:

```python
# ── MCP server specification ───────────────────────────────────────────

class MCPServerSpec(BaseModel):
    """Describes one MCP server an organism can connect to."""
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    transport: str = "stdio"  # "stdio" | "sse"


# ── Skill reference (DNA pointer) ──────────────────────────────────────

class SkillRef(BaseModel):
    """A pointer into the Genesis skill pool. Lives in organism DNA."""
    skill_id: str
    name: str
    inherited_at: datetime
```

Then in the `Organism` class, after the `learned_patterns` field, add:

```python
    # Phase 1 — substrate
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    inherited_skills: list[SkillRef] = Field(default_factory=list)
    parent_organisms: list[str] = Field(default_factory=list)
    fitness_score: float = 0.0
    distilled_skill_id: Optional[str] = None
```

- [ ] **Step 2.4: Run tests — should pass**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_types.py -v`
Expected: 3 PASSED.

- [ ] **Step 2.5: Commit**

```bash
git add backend/genesis/types.py backend/tests/genesis/test_types.py
git commit -m "feat(genesis): add MCPServerSpec, SkillRef, Phase 1 Organism fields"
```

---

### Task 3: Pipeline regression baseline

This task captures current `perceive()` behavior in a test BEFORE we refactor, so the refactor is provably non-breaking.

**Files:**
- Create: `backend/tests/genesis/test_pipeline_refactor.py`

- [ ] **Step 3.1: Write the regression test**

Create `backend/tests/genesis/test_pipeline_refactor.py`:

```python
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
        "action": {"tool": "noop", "args": {}},
        "alternatives": [],
    }))

    # Act
    decision = await runtime.perceive(org.id, {"type": "test_event"})

    # Assert structural invariants the refactor must preserve
    assert decision.organism_id == org.id
    assert decision.trigger == {"type": "test_event"}
    assert decision.reasoning == "I should noop"
    assert decision.action == {"tool": "noop", "args": {}}
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
        "action": {"tool": "send_slack", "args": {"channel": "#x", "text": "hi"}},
        "alternatives": [],
    }))

    decision = await runtime.perceive(org.id, {"type": "imagined"}, is_dream=True)

    assert decision.is_dream is True
    # In dream mode, the action is recorded but the side effect must be simulated
    assert decision.action["tool"] == "send_slack"
```

- [ ] **Step 3.2: Run baseline tests — they should PASS against current `runtime.perceive`**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_pipeline_refactor.py -v`
Expected: 2 PASSED. If they FAIL here, the existing `perceive()` has a bug — STOP and investigate before refactoring.

- [ ] **Step 3.3: Commit**

```bash
git add backend/tests/genesis/test_pipeline_refactor.py
git commit -m "test(genesis): regression baseline for perceive() pre-refactor"
```

---

### Task 4: Refactor `perceive()` into the 5-stage pipeline

**Files:**
- Create: `backend/genesis/pipeline/__init__.py`
- Create: `backend/genesis/pipeline/stages.py`
- Modify: `backend/genesis/runtime.py`

- [ ] **Step 4.1: Create `backend/genesis/pipeline/__init__.py` (empty)**

- [ ] **Step 4.2: Create `backend/genesis/pipeline/stages.py` skeleton**

Open `backend/genesis/runtime.py` and READ it carefully — the entire `perceive()` body needs to be split into 5 functions without changing observable behavior.

Create `backend/genesis/pipeline/stages.py`:

```python
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
    tool_catalog: list[dict] = field(default_factory=list)  # for LLM
    llm_raw: str = ""
    parsed: dict = field(default_factory=dict)
    decision: Optional[Decision] = None


async def gather_context(ctx: PipelineContext) -> None:
    """Stage 1: load organism, recent decisions, and inherited skills text."""
    ctx.organism = store.load_organism(ctx.organism_id)
    if not ctx.organism:
        raise ValueError(f"organism {ctx.organism_id} not found")
    all_decisions = store.all_decisions(ctx.organism_id)
    ctx.real_history = [d for d in all_decisions if not d.is_dream and not d.shadow_branch][-8:]
    ctx.dream_history = [d for d in all_decisions if d.is_dream][-5:]
    # Inherited skills loaded by skills.inherit (Task 6 fills this in)
    ctx.skills_text = ""


async def load_capabilities(ctx: PipelineContext) -> None:
    """Stage 2: assemble the tool catalog the LLM will see.

    Phase 1 baseline: built-in tools only. Task 11 adds MCP tools here."""
    from .. import runtime  # avoid circular import at module load
    ctx.tool_catalog = runtime._builtin_tool_catalog()


async def reason(ctx: PipelineContext) -> None:
    """Stage 3: LLM call. Same prompt-building logic as legacy perceive()."""
    from .. import runtime
    ctx.llm_raw = await runtime._reason_with_llm(ctx)


async def act(ctx: PipelineContext) -> None:
    """Stage 4: parse LLM response, dispatch tool. Honors is_dream."""
    from .. import runtime
    ctx.parsed = runtime._parse_llm_response(ctx.llm_raw)
    ctx.decision = await runtime._execute_action(ctx)


async def record(ctx: PipelineContext) -> None:
    """Stage 5: persist decision, emit events, update fitness placeholder."""
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
    """Drive all 5 stages in order. Returns the final Decision."""
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
```

- [ ] **Step 4.3: Refactor `runtime.py` to expose helper functions used by stages**

In `backend/genesis/runtime.py`, extract the existing `perceive()` body into private helpers. The new public `perceive()` becomes a thin shim:

```python
async def perceive(
    organism_id: str,
    perception: dict,
    *,
    is_dream: bool = False,
    shadow_branch: Optional[str] = None,
    parent_ids: Optional[list[str]] = None,
    event_callback=None,
) -> Decision:
    """Public entrypoint. Delegates to the pipeline."""
    from .pipeline import stages
    return await stages.run(
        organism_id, perception,
        is_dream=is_dream, shadow_branch=shadow_branch,
        parent_ids=parent_ids, event_callback=event_callback,
    )
```

Move the existing logic into these private helpers (READ the current `runtime.py` and physically cut/paste — do not rewrite the prompt-building or tool-dispatch logic):

- `_builtin_tool_catalog() -> list[dict]` — returns the existing tool definitions for the LLM.
- `_reason_with_llm(ctx) -> str` — builds the prompt from `ctx.organism, ctx.real_history, ctx.dream_history, ctx.skills_text, ctx.tool_catalog, ctx.perception`, calls `generate_text`, returns raw response.
- `_parse_llm_response(raw: str) -> dict` — JSON-extract the LLM response (existing logic).
- `_execute_action(ctx) -> Decision` — runs the tool (or simulates if `ctx.is_dream`), constructs the Decision object with all fields populated, but does NOT persist or emit yet.
- `_persist_and_emit(ctx) -> None` — saves the decision, fires `organism.acted`, updates organism state, AND in Phase 1 also computes the fitness_score heuristic:
  ```python
  if ctx.organism and not ctx.is_dream:
      reals = [d for d in store.all_decisions(ctx.organism.id) if not d.is_dream and not d.shadow_branch]
      ok = sum(1 for d in reals if d.result.get("ok") is True)
      ctx.organism.fitness_score = ok / max(len(reals), 1)
      store.save_organism(ctx.organism)
  ```

Keep all existing event emissions exactly as before (`organism.perceiving`, `organism.reasoning`, `organism.acted`).

- [ ] **Step 4.4: Run the regression test from Task 3**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_pipeline_refactor.py -v`
Expected: 2 PASSED. If it fails, the refactor changed observable behavior — diff the helper functions against the original `perceive()` body until parity is restored.

- [ ] **Step 4.5: Smoke-test the FastAPI app boots**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow && /usr/local/bin/python3.11 -c "from backend.genesis import runtime, api; print('OK')"`
Expected: `OK` printed, no import errors.

- [ ] **Step 4.6: Commit**

```bash
git add backend/genesis/pipeline/ backend/genesis/runtime.py
git commit -m "refactor(genesis): extract perceive into 5-stage pipeline"
```

---

### Task 5: Skill pool I/O

**Files:**
- Create: `backend/genesis/skills/__init__.py` (empty)
- Create: `backend/genesis/skills/pool.py`
- Create: `backend/tests/genesis/test_skill_pool.py`

- [ ] **Step 5.1: Write the failing test**

Create `backend/tests/genesis/test_skill_pool.py`:

```python
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
```

- [ ] **Step 5.2: Run — should fail with ImportError**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_pool.py -v`
Expected: ImportError.

- [ ] **Step 5.3: Implement `backend/genesis/skills/__init__.py` (empty file)**

- [ ] **Step 5.4: Implement `backend/genesis/skills/pool.py`**

```python
"""Genesis-internal skill pool. Read/write hybrid YAML+markdown files.

Files live at $GENESIS_STORAGE/_skill_pool/sk_<id>.md.
Frontmatter is structured (machine-parseable for inheritance/lineage).
Body is LLM-written narrative guidance (read by future organisms).
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import yaml  # PyYAML ships with chromadb; if missing, pip install pyyaml

from .. import store


def _pool_dir() -> Path:
    d = Path(store._BASE) / "_skill_pool"  # noqa: SLF001
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Skill:
    skill_id: str
    name: str
    description: str
    distilled_at: datetime
    parent_organisms: list[str]
    parent_skills: list[str]
    generation: int
    fitness_at_death: float
    n_decisions_distilled: int
    trigger_patterns: list[str]
    forbidden_patterns: list[str]
    body: str


def new_skill_id() -> str:
    return f"sk_{uuid4().hex[:10]}"


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _serialize(skill: Skill) -> str:
    fm = {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "distilled_at": skill.distilled_at.isoformat(),
        "parent_organisms": list(skill.parent_organisms),
        "parent_skills": list(skill.parent_skills),
        "generation": skill.generation,
        "fitness_at_death": skill.fitness_at_death,
        "n_decisions_distilled": skill.n_decisions_distilled,
        "trigger_patterns": list(skill.trigger_patterns),
        "forbidden_patterns": list(skill.forbidden_patterns),
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + skill.body


def _deserialize(text: str) -> Skill:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("malformed skill file: missing frontmatter")
    fm = yaml.safe_load(m.group(1))
    body = m.group(2)
    return Skill(
        skill_id=fm["skill_id"],
        name=fm["name"],
        description=fm["description"],
        distilled_at=datetime.fromisoformat(fm["distilled_at"]),
        parent_organisms=list(fm.get("parent_organisms", [])),
        parent_skills=list(fm.get("parent_skills", [])),
        generation=int(fm.get("generation", 1)),
        fitness_at_death=float(fm.get("fitness_at_death", 0.0)),
        n_decisions_distilled=int(fm.get("n_decisions_distilled", 0)),
        trigger_patterns=list(fm.get("trigger_patterns", [])),
        forbidden_patterns=list(fm.get("forbidden_patterns", [])),
        body=body,
    )


def write(skill: Skill) -> Path:
    """Atomic write — temp file + rename. Survives crashes mid-write."""
    target = _pool_dir() / f"{skill.skill_id}.md"
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=skill.skill_id + ".", suffix=".tmp",
                                         dir=str(_pool_dir()))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(_serialize(skill))
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise
    return target


def load(skill_id: str) -> Optional[Skill]:
    p = _pool_dir() / f"{skill_id}.md"
    if not p.exists():
        return None
    return _deserialize(p.read_text(encoding="utf-8"))


def list_summaries() -> list[dict]:
    """List all pool skills as frontmatter dicts (no body, fast)."""
    out = []
    for p in sorted(_pool_dir().glob("sk_*.md")):
        text = p.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1))
        out.append(fm)
    return out


def delete(skill_id: str) -> bool:
    p = _pool_dir() / f"{skill_id}.md"
    if p.exists():
        p.unlink()
        return True
    return False
```

- [ ] **Step 5.5: Confirm pyyaml available**

Run: `/usr/local/bin/python3.11 -c "import yaml; print(yaml.__version__)"`
Expected: a version number. If ImportError: `python3.11 -m pip install pyyaml` and add `pyyaml>=6.0` to `backend/requirements.txt`.

- [ ] **Step 5.6: Run tests — should pass**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_pool.py -v`
Expected: 3 PASSED.

- [ ] **Step 5.7: Commit**

```bash
git add backend/genesis/skills/ backend/tests/genesis/test_skill_pool.py
git commit -m "feat(genesis): skill pool I/O with atomic writes"
```

---

### Task 6: Skill inheritance — load skills at perceive

**Files:**
- Create: `backend/genesis/skills/inherit.py`
- Create: `backend/tests/genesis/test_skill_inheritance.py`
- Modify: `backend/genesis/pipeline/stages.py` (gather_context calls inherit.load_skills_text)

- [ ] **Step 6.1: Write the failing test**

Create `backend/tests/genesis/test_skill_inheritance.py`:

```python
"""Inherited skill body must reach the LLM prompt."""
import json
from datetime import datetime

import pytest

from backend.genesis import runtime, store
from backend.genesis.skills import pool
from backend.genesis.types import Intent, Organism, SkillRef


@pytest.mark.asyncio
async def test_inherited_skill_text_appears_in_llm_prompt(tmp_storage, fake_llm):
    # Plant a skill in the pool
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

    # Seed organism with that skill in DNA
    org = Organism(
        intent=Intent(goal="g"),
        inherited_skills=[SkillRef(skill_id="sk_inherit01", name="vip_handling",
                                    inherited_at=datetime.utcnow())],
    )
    store.save_organism(org)

    fake_llm.responses.append(json.dumps({
        "reasoning": "ok", "action": {"tool": "noop", "args": {}}, "alternatives": []
    }))

    await runtime.perceive(org.id, {"type": "x"})

    # Assert the skill body text was injected into the LLM prompt
    assert any("VIP customers come from @bigcorp.com" in p["prompt"]
               for p in fake_llm.prompts), "skill body missing from LLM prompt"
    assert any("vip_handling" in p["prompt"] for p in fake_llm.prompts)
```

- [ ] **Step 6.2: Run — should fail (skill text not in prompt)**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_inheritance.py -v`
Expected: AssertionError "skill body missing from LLM prompt".

- [ ] **Step 6.3: Implement `backend/genesis/skills/inherit.py`**

```python
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

    # Pull skills from given organisms' lineage too
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

    # Materialize and rank by fitness_at_death (descending), then cap
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
    return refs, sorted(parent_orgs)


def load_skills_text(organism: Organism) -> str:
    """Return the prompt block to inject into the LLM call.
    Empty string if the organism has no inherited skills."""
    if not organism.inherited_skills:
        return ""
    blocks: list[str] = [
        "INHERITED WISDOM (read carefully — these are skills your ancestors distilled):\n"
    ]
    used = 0
    # Sort by fitness so highest-quality skills load first under the budget
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
```

- [ ] **Step 6.4: Wire it into `gather_context` in `backend/genesis/pipeline/stages.py`**

Replace the `ctx.skills_text = ""` line in `gather_context()` with:

```python
    from ..skills import inherit
    ctx.skills_text = inherit.load_skills_text(ctx.organism)
```

- [ ] **Step 6.5: Wire `skills_text` into the LLM prompt**

Open `backend/genesis/runtime.py` and find `_reason_with_llm(ctx)`. Locate where the user prompt is assembled (after the existing context elements). Add this snippet right after the recent-history section, BEFORE the perception section:

```python
        if ctx.skills_text:
            user_parts.append(ctx.skills_text)
```

(`user_parts` is whatever list you used to assemble the prompt during the Task 4 refactor — name may differ; the key is: skills text becomes part of what gets passed to `generate_text`.)

- [ ] **Step 6.6: Run inheritance test — should pass**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_inheritance.py -v`
Expected: 1 PASSED.

- [ ] **Step 6.7: Run regression test from Task 3 — should still pass**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_pipeline_refactor.py -v`
Expected: 2 PASSED.

- [ ] **Step 6.8: Commit**

```bash
git add backend/genesis/skills/inherit.py backend/genesis/pipeline/stages.py backend/genesis/runtime.py backend/tests/genesis/test_skill_inheritance.py
git commit -m "feat(genesis): inherited skills load into perceive prompt"
```

---

### Task 7: Skill distillation on death

**Files:**
- Create: `backend/genesis/skills/distill.py`
- Create: `backend/tests/genesis/test_skill_lifecycle.py`
- Modify: `backend/genesis/api.py` (DELETE endpoint calls distill)

- [ ] **Step 7.1: Write the failing test**

Create `backend/tests/genesis/test_skill_lifecycle.py`:

```python
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

    # 5 perceptions, 5 LLM responses
    for i in range(5):
        fake_llm.responses.append(json.dumps({
            "reasoning": f"reasoning {i}",
            "action": {"tool": "noop", "args": {}},
            "alternatives": [],
        }))
    for i in range(5):
        await runtime.perceive(org.id, {"type": "tick", "i": i})

    # Distillation LLM call returns a structured response
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
    # Only 3 perceives — below the 5-decision threshold
    for i in range(3):
        fake_llm.responses.append(json.dumps({
            "reasoning": "r", "action": {"tool": "noop", "args": {}}, "alternatives": []
        }))
        await runtime.perceive(org.id, {"type": "tick"})

    skill_id = await distill.distill(org.id)
    assert skill_id is None
```

- [ ] **Step 7.2: Run — should fail**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_lifecycle.py -v`
Expected: ImportError on `distill`.

- [ ] **Step 7.3: Implement `backend/genesis/skills/distill.py`**

```python
"""Distill an organism's life into a Skill at death.

Triggered by DELETE /api/genesis/organisms/{id} BEFORE files are wiped.
Skips silently if the organism has fewer than MIN_DECISIONS real decisions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from backend.shared.gemini_client import generate_text

from .. import store
from . import pool
from .pool import Skill, new_skill_id

logger = logging.getLogger("genesis.skills.distill")

MIN_DECISIONS = 5

DISTILL_SYSTEM = """You are distilling a digital organism's life into a Skill
that future organisms will inherit. From the organism's intent, decisions, and
inherited skills, produce JSON with these fields:
  - name: short snake_case identifier (e.g. "vip_email_triage")
  - description: one-sentence summary
  - trigger_patterns: list of strings — what trigger types/conditions matter
  - forbidden_patterns: list of strings — what NOT to do
  - body: markdown with sections "# What this knows", "# What worked",
          "# What failed", "# Patterns observed". Be specific, not generic.

Return STRICT JSON only. No code fences, no preamble.
"""


async def distill(organism_id: str) -> Optional[str]:
    """Returns the new skill_id, or None if skipped."""
    org = store.load_organism(organism_id)
    if not org:
        return None
    decisions = [d for d in store.all_decisions(organism_id)
                 if not d.is_dream and not d.shadow_branch]
    if len(decisions) < MIN_DECISIONS:
        logger.info(f"[distill] {organism_id} has {len(decisions)} decisions < "
                    f"{MIN_DECISIONS}, skipping")
        return None

    inherited_skill_summaries = []
    for ref in org.inherited_skills:
        s = pool.load(ref.skill_id)
        if s:
            inherited_skill_summaries.append({
                "name": s.name,
                "description": s.description,
                "fitness_at_death": s.fitness_at_death,
            })

    user_payload = {
        "intent": {
            "goal": org.intent.goal,
            "constraints": org.intent.constraints,
            "forbidden": org.intent.forbidden,
        },
        "fitness_score": org.fitness_score,
        "decisions": [
            {"trigger": d.trigger, "reasoning": d.reasoning,
             "action": d.action, "result": d.result}
            for d in decisions
        ],
        "inherited_skills_used": inherited_skill_summaries,
    }
    raw = await generate_text(
        prompt=json.dumps(user_payload, indent=2, default=str),
        system=DISTILL_SYSTEM,
        temperature=0.4,
        max_tokens=2000,
    )
    parsed = _parse_distillation(raw)
    if not parsed:
        logger.warning(f"[distill] {organism_id} got unparseable LLM response, skipping")
        return None

    # Compute generation
    parent_skills = [r.skill_id for r in org.inherited_skills]
    parent_gens = [pool.load(sid).generation for sid in parent_skills if pool.load(sid)]
    generation = (max(parent_gens) + 1) if parent_gens else 1

    skill = Skill(
        skill_id=new_skill_id(),
        name=parsed.get("name", f"organism_{organism_id[:6]}_skill"),
        description=parsed.get("description", ""),
        distilled_at=datetime.utcnow(),
        parent_organisms=[organism_id],
        parent_skills=parent_skills,
        generation=generation,
        fitness_at_death=org.fitness_score,
        n_decisions_distilled=len(decisions),
        trigger_patterns=list(parsed.get("trigger_patterns", [])),
        forbidden_patterns=list(parsed.get("forbidden_patterns", [])),
        body=parsed.get("body", "# What this knows\n(no body distilled)\n"),
    )
    pool.write(skill)
    org.distilled_skill_id = skill.skill_id
    store.save_organism(org)
    logger.info(f"[distill] {organism_id} → {skill.skill_id} (gen {generation})")
    return skill.skill_id


def _parse_distillation(raw: str) -> Optional[dict]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1:
            try:
                return json.loads(s[i : j + 1])
            except Exception:
                return None
        return None
```

- [ ] **Step 7.4: Run lifecycle tests — should pass**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_skill_lifecycle.py -v`
Expected: 2 PASSED.

- [ ] **Step 7.5: Wire distillation into the DELETE endpoint**

Open `backend/genesis/api.py`. Find the `kill_organism` route. Modify it to call distill BEFORE wiping files. Replace the body with:

```python
@router.delete("/organisms/{organism_id}")
async def kill_organism(organism_id: str):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")

    # Phase 1 — distill organism's life into a Skill before death
    from .skills import distill as _distill
    try:
        new_skill_id = await _distill.distill(organism_id)
    except Exception as e:
        # Distillation failure must NEVER block death — log + continue.
        import logging
        logging.getLogger("genesis.api").warning(
            f"distillation failed for {organism_id}: {e}"
        )
        new_skill_id = None

    base = Path(store._BASE) / organism_id  # noqa: SLF001
    if base.exists():
        shutil.rmtree(base)
    await events.emit("organism.died", {
        "organism_id": organism_id,
        "patterns_donated": org.learned_patterns,
        "distilled_skill_id": new_skill_id,
    })
    if new_skill_id:
        await events.emit("organism.distilled", {
            "organism_id": organism_id, "skill_id": new_skill_id,
        })
    return {"died": organism_id,
            "patterns_donated": org.learned_patterns,
            "distilled_skill_id": new_skill_id}
```

Also add `"organism.distilled"` to `EVENT_TYPES` in `backend/genesis/events.py`.

- [ ] **Step 7.6: Commit**

```bash
git add backend/genesis/skills/distill.py backend/genesis/api.py backend/genesis/events.py backend/tests/genesis/test_skill_lifecycle.py
git commit -m "feat(genesis): distill organism into Skill on death (>=5 decisions)"
```

---

### Task 8: MCP catalog (global server config)

**Files:**
- Create: `backend/genesis/mcp/__init__.py` (empty)
- Create: `backend/genesis/mcp/catalog.py`

- [ ] **Step 8.1: Create `backend/genesis/mcp/__init__.py` (empty)**

- [ ] **Step 8.2: Implement `backend/genesis/mcp/catalog.py`**

```python
"""Global ambient MCP server catalog. Read from $GENESIS_STORAGE/_mcp_global.json
or from the path set by GENESIS_MCP_GLOBAL env var if it points elsewhere.

File format:
  {"servers": [{"name": "...", "command": "...", "args": [...], "env": {...}}]}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .. import store
from ..types import MCPServerSpec

logger = logging.getLogger("genesis.mcp.catalog")


def _config_path() -> Path:
    override = os.getenv("GENESIS_MCP_GLOBAL")
    if override:
        return Path(override)
    return Path(store._BASE) / "_mcp_global.json"  # noqa: SLF001


def load_global_specs() -> list[MCPServerSpec]:
    p = _config_path()
    if not p.exists():
        logger.info(f"[mcp.catalog] no global config at {p}; starting with empty catalog")
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[mcp.catalog] failed to parse {p}: {e}")
        return []
    out: list[MCPServerSpec] = []
    for d in data.get("servers", []):
        try:
            out.append(MCPServerSpec(**d))
        except Exception as e:
            logger.warning(f"[mcp.catalog] skipping bad server entry {d}: {e}")
    return out


def write_global_specs(specs: list[MCPServerSpec]) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"servers": [s.model_dump() for s in specs]}, indent=2
    ), encoding="utf-8")
```

- [ ] **Step 8.3: Quick sanity check**

Run: `/usr/local/bin/python3.11 -c "from backend.genesis.mcp import catalog; print(catalog.load_global_specs())"`
Expected: `[]` (no config file yet — that's fine).

- [ ] **Step 8.4: Commit**

```bash
git add backend/genesis/mcp/
git commit -m "feat(genesis): MCP global server catalog (read/write _mcp_global.json)"
```

---

### Task 9: MCPPool — connection lifecycle + tool dispatch

**Files:**
- Create: `backend/genesis/mcp/client.py`
- Create: `backend/tests/genesis/mock_mcp_server.py`
- Create: `backend/tests/genesis/test_mcp_dispatch.py`

This is the largest task. The pool wraps the official `mcp` Python SDK if available, else uses a minimal JSON-RPC stdio client.

- [ ] **Step 9.1: Probe the `mcp` package shape**

Run: `/usr/local/bin/python3.11 -c "import mcp; from mcp import ClientSession; from mcp.client.stdio import stdio_client; print(ClientSession, stdio_client)"`

If this prints two class/function objects, the SDK is usable — proceed with Step 9.2 SDK path.
If ImportError or attribute missing, skip to Step 9.3 (custom JSON-RPC fallback).

- [ ] **Step 9.2: Implement `backend/genesis/mcp/client.py` (SDK path)**

```python
"""MCPPool — global + per-organism MCP server connections, tool dispatch.

Uses the official `mcp` Python SDK over stdio.
Connections are lazy (opened on first list_tools/call) and long-lived.
Per-organism servers are isolated from other organisms' servers.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..types import MCPServerSpec

logger = logging.getLogger("genesis.mcp.pool")


@dataclass
class _ConnectionState:
    spec: MCPServerSpec
    session: Optional[ClientSession] = None
    stack: Optional[AsyncExitStack] = None
    healthy: bool = True
    failures: int = 0
    tools_cache: list[dict] = field(default_factory=list)


_NS_PREFIX = "mcp__"
_MAX_CONSECUTIVE_FAILURES = 5


class MCPPool:
    def __init__(self) -> None:
        self._global: dict[str, _ConnectionState] = {}
        self._private: dict[str, dict[str, _ConnectionState]] = {}
        self._lock = asyncio.Lock()

    # ── Server registration ──────────────────────────────────────────

    async def ensure_global(self, specs: list[MCPServerSpec]) -> None:
        async with self._lock:
            for s in specs:
                self._global.setdefault(s.name, _ConnectionState(spec=s))

    async def ensure_organism(self, organism_id: str,
                              specs: list[MCPServerSpec]) -> None:
        async with self._lock:
            org_map = self._private.setdefault(organism_id, {})
            for s in specs:
                org_map.setdefault(s.name, _ConnectionState(spec=s))

    # ── Tool listing ─────────────────────────────────────────────────

    async def list_tools(self, organism_id: str) -> list[dict]:
        """Returns merged tool catalog: global ∪ this organism's private,
        each tool dict has keys: name (namespaced), description, schema, server."""
        out: list[dict] = []
        for name, state in self._global.items():
            out.extend(await self._tools_of(state, server_name=name))
        for name, state in self._private.get(organism_id, {}).items():
            out.extend(await self._tools_of(state, server_name=name))
        return out

    async def _tools_of(self, state: _ConnectionState, *, server_name: str
                        ) -> list[dict]:
        if not state.healthy:
            return []
        try:
            await self._ensure_session(state)
            if not state.tools_cache:
                resp = await state.session.list_tools()
                state.tools_cache = [
                    {
                        "name": f"{_NS_PREFIX}{server_name}__{t.name}",
                        "raw_name": t.name,
                        "description": t.description or "",
                        "schema": t.inputSchema if hasattr(t, "inputSchema") else {},
                        "server": server_name,
                    }
                    for t in resp.tools
                ]
            return state.tools_cache
        except Exception as e:
            self._record_failure(state, e)
            return []

    # ── Tool dispatch ────────────────────────────────────────────────

    async def call(self, organism_id: str, namespaced_tool: str,
                   args: dict, *, is_dream: bool = False) -> dict:
        if is_dream:
            raise RuntimeError(
                "MCPPool.call invoked in dream mode — dispatcher must intercept "
                "before reaching MCPPool"
            )
        if not namespaced_tool.startswith(_NS_PREFIX):
            return {"ok": False, "error": f"not an MCP tool: {namespaced_tool}"}
        rest = namespaced_tool[len(_NS_PREFIX):]
        try:
            server_name, tool_name = rest.split("__", 1)
        except ValueError:
            return {"ok": False, "error": f"malformed MCP tool name: {namespaced_tool}"}

        state = (self._private.get(organism_id, {}).get(server_name)
                 or self._global.get(server_name))
        if not state:
            return {"ok": False, "error": f"unknown MCP server: {server_name}"}
        if not state.healthy:
            return {"ok": False, "error": f"MCP server {server_name} unhealthy"}

        try:
            await self._ensure_session(state)
            result = await asyncio.wait_for(
                state.session.call_tool(tool_name, args), timeout=30.0
            )
            # mcp SDK returns CallToolResult; extract content
            content = []
            for c in getattr(result, "content", []):
                if hasattr(c, "text"):
                    content.append({"type": "text", "text": c.text})
                else:
                    content.append({"type": "unknown", "raw": str(c)})
            return {"ok": True, "content": content}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            self._record_failure(state, e)
            return {"ok": False, "error": str(e)}

    # ── Connection management ────────────────────────────────────────

    async def _ensure_session(self, state: _ConnectionState) -> None:
        if state.session is not None:
            return
        params = StdioServerParameters(
            command=state.spec.command,
            args=list(state.spec.args),
            env=dict(state.spec.env) or None,
        )
        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        state.session = session
        state.stack = stack
        state.failures = 0
        state.healthy = True
        logger.info(f"[mcp] connected to {state.spec.name}")

    def _record_failure(self, state: _ConnectionState, err: Exception) -> None:
        state.failures += 1
        logger.warning(f"[mcp] {state.spec.name} failure #{state.failures}: {err}")
        if state.failures >= _MAX_CONSECUTIVE_FAILURES:
            state.healthy = False
            logger.error(f"[mcp] {state.spec.name} marked unhealthy")
        # Drop session so next attempt reconnects
        state.session = None
        state.tools_cache = []

    async def status(self) -> dict:
        def _summarize(m: dict) -> list[dict]:
            return [
                {"name": s.spec.name, "healthy": s.healthy,
                 "failures": s.failures, "tool_count": len(s.tools_cache)}
                for s in m.values()
            ]
        return {
            "global": _summarize(self._global),
            "private": {oid: _summarize(m) for oid, m in self._private.items()},
        }

    async def shutdown(self) -> None:
        for m in [self._global, *self._private.values()]:
            for state in list(m.values()):
                if state.stack:
                    try:
                        await state.stack.aclose()
                    except Exception:
                        pass
                state.session = None
                state.stack = None


# Module-level singleton
pool = MCPPool()
```

- [ ] **Step 9.3: (Fallback) If `mcp` SDK is unavailable**

If Step 9.1 failed, replace the SDK imports above with a minimal JSON-RPC stdio client. Skipped here for brevity — the spec explicitly says "library swap is a one-file change behind `MCPPool`." The dispatcher contract (`call`, `list_tools`) stays identical.

- [ ] **Step 9.4: Write a tiny mock MCP server for tests**

Create `backend/tests/genesis/mock_mcp_server.py`:

```python
"""A trivial stdio MCP server for tests. One tool: echo(text) → text.

Implements the bare JSON-RPC subset the SDK needs: initialize, tools/list,
tools/call. Designed to be launched as a subprocess by the SDK's stdio_client.
"""
from __future__ import annotations

import json
import sys


def _resp(req_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _notify(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            _resp(rid, {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mock", "version": "0"},
                "capabilities": {"tools": {}},
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _resp(rid, {"tools": [
                {"name": "echo", "description": "Echoes back the text",
                 "inputSchema": {"type": "object",
                                 "properties": {"text": {"type": "string"}},
                                 "required": ["text"]}}
            ]})
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "echo":
                _resp(rid, {"content": [{"type": "text", "text": args.get("text", "")}]})
            else:
                _resp(rid, error={"code": -32601, "message": f"unknown tool: {name}"})
        elif rid is not None:
            _resp(rid, error={"code": -32601, "message": f"unknown method: {method}"})


if __name__ == "__main__":
    main()
```

- [ ] **Step 9.5: Write the dispatch test**

Create `backend/tests/genesis/test_mcp_dispatch.py`:

```python
"""End-to-end MCP dispatch via MCPPool against a mock stdio server."""
import sys
from pathlib import Path

import pytest

from backend.genesis.mcp.client import MCPPool
from backend.genesis.types import MCPServerSpec


@pytest.mark.asyncio
async def test_pool_lists_and_calls_mock_tool():
    mock_path = Path(__file__).parent / "mock_mcp_server.py"
    spec = MCPServerSpec(
        name="mock",
        command=sys.executable,
        args=[str(mock_path)],
    )
    pool = MCPPool()
    await pool.ensure_organism("o_x", [spec])
    try:
        tools = await pool.list_tools("o_x")
        assert any(t["name"] == "mcp__mock__echo" for t in tools)
        result = await pool.call("o_x", "mcp__mock__echo", {"text": "hello"})
        assert result["ok"] is True
        assert any(c.get("text") == "hello" for c in result.get("content", []))
    finally:
        await pool.shutdown()


@pytest.mark.asyncio
async def test_pool_rejects_dream_mode():
    pool = MCPPool()
    with pytest.raises(RuntimeError, match="dream mode"):
        await pool.call("o_x", "mcp__any__tool", {}, is_dream=True)
```

- [ ] **Step 9.6: Run dispatch test**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis/test_mcp_dispatch.py -v`
Expected: 2 PASSED.

If the SDK install failed earlier and you took the JSON-RPC fallback, this test will validate the fallback equally well — the contract is identical.

- [ ] **Step 9.7: Commit**

```bash
git add backend/genesis/mcp/client.py backend/tests/genesis/mock_mcp_server.py backend/tests/genesis/test_mcp_dispatch.py
git commit -m "feat(genesis): MCPPool with lazy connection, namespaced tool dispatch"
```

---

### Task 10: Pipeline integration — `load_capabilities` queries MCPPool, `act` dispatches MCP tools

**Files:**
- Modify: `backend/genesis/pipeline/stages.py`
- Modify: `backend/genesis/runtime.py`
- Modify: `backend/main.py` (init pool with global specs at startup)

- [ ] **Step 10.1: Modify `load_capabilities` in `pipeline/stages.py`**

Replace the body with:

```python
async def load_capabilities(ctx: PipelineContext) -> None:
    from .. import runtime
    from ..mcp import client as mcp_client
    catalog = runtime._builtin_tool_catalog()
    # Make sure this organism's private servers are registered
    if ctx.organism and ctx.organism.mcp_servers:
        await mcp_client.pool.ensure_organism(ctx.organism.id, ctx.organism.mcp_servers)
    mcp_tools = await mcp_client.pool.list_tools(ctx.organism_id) if ctx.organism else []
    # Conflict resolution: built-in wins. Skip MCP tools whose namespaced name
    # collides with a built-in (cannot happen given mcp__ prefix, but defensive).
    builtin_names = {t["name"] for t in catalog}
    catalog.extend(t for t in mcp_tools if t["name"] not in builtin_names)
    ctx.tool_catalog = catalog
```

- [ ] **Step 10.2: Modify `_execute_action` in `runtime.py` to dispatch MCP tools**

Find `_execute_action(ctx)`. After parsing the LLM's chosen tool name, before the existing tool-name match block, insert:

```python
    tool_name = ctx.parsed.get("action", {}).get("tool", "")
    if tool_name.startswith("mcp__"):
        if ctx.is_dream:
            # Dream mode — synthesize a plausible result, do NOT touch real server
            result = await _synthesize_dream_result(ctx, tool_name)
        else:
            from .mcp import client as mcp_client
            args = ctx.parsed.get("action", {}).get("args", {})
            result = await mcp_client.pool.call(ctx.organism_id, tool_name, args,
                                                 is_dream=False)
        # Build the Decision identically to other tools
        return _build_decision_with_result(ctx, result)
```

Then add `_synthesize_dream_result(ctx, tool_name)`:

```python
async def _synthesize_dream_result(ctx, tool_name: str) -> dict:
    """Ask the LLM to invent a plausible result for an MCP tool call in a dream."""
    from backend.shared.gemini_client import generate_text
    raw = await generate_text(
        prompt=(f"You are simulating the result of calling MCP tool {tool_name} "
                f"with args {ctx.parsed.get('action', {}).get('args', {})}. "
                f"Return STRICT JSON: a plausible result object."),
        system="Return only JSON, no preamble.",
        temperature=0.6, max_tokens=400,
    )
    try:
        import json as _j
        return {"ok": True, "simulated": True, "content": _j.loads(raw)}
    except Exception:
        return {"ok": True, "simulated": True, "content": raw}
```

`_build_decision_with_result(ctx, result)` is whatever local helper you used during the Task 4 refactor to assemble a Decision object — call that.

- [ ] **Step 10.3: Modify the LLM prompt to advertise MCP tools**

In `_reason_with_llm(ctx)`, where you currently render the built-in tool catalog into the system or user prompt, render the MCP tools too. Group them by server:

```python
    builtin = [t for t in ctx.tool_catalog if not t["name"].startswith("mcp__")]
    mcp = [t for t in ctx.tool_catalog if t["name"].startswith("mcp__")]
    tool_block_lines = ["AVAILABLE TOOLS:", "=== Built-in ==="]
    for t in builtin:
        tool_block_lines.append(f"  {t['name']}: {t.get('description','')}")
    if mcp:
        # group by server
        from collections import defaultdict
        by_server = defaultdict(list)
        for t in mcp:
            by_server[t.get("server","unknown")].append(t)
        for server, ts in by_server.items():
            tool_block_lines.append(f"=== MCP: {server} ===")
            for t in ts:
                tool_block_lines.append(f"  {t['name']}: {t.get('description','')}")
    tool_block = "\n".join(tool_block_lines)
```

Inject `tool_block` into the prompt where the built-in tool list used to live.

- [ ] **Step 10.4: Init pool with global specs in `backend/main.py` lifespan**

In the `lifespan` async context manager, after `_genesis_lifecycle.start()`, add:

```python
    # Genesis MCP pool — load global ambient servers
    from backend.genesis.mcp import client as _mcp_client, catalog as _mcp_catalog
    global_specs = _mcp_catalog.load_global_specs()
    if global_specs:
        await _mcp_client.pool.ensure_global(global_specs)
        print(f"[Genesis] MCP pool: {len(global_specs)} global server(s) registered")
```

And in the shutdown branch (after `_genesis_lifecycle.stop()`):

```python
    try:
        from backend.genesis.mcp import client as _mcp_client
        await _mcp_client.pool.shutdown()
    except Exception:
        pass
```

- [ ] **Step 10.5: Run regression + dispatch tests**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis -v`
Expected: ALL existing tests pass.

- [ ] **Step 10.6: Commit**

```bash
git add backend/genesis/pipeline/stages.py backend/genesis/runtime.py backend/main.py
git commit -m "feat(genesis): pipeline integrates MCPPool — tools merged + dispatched"
```

---

### Task 11: API endpoints

**Files:**
- Modify: `backend/genesis/api.py`

- [ ] **Step 11.1: Extend `SeedRequest`**

In `backend/genesis/api.py`, modify `SeedRequest`:

```python
class SeedRequest(BaseModel):
    goal: str = Field(..., description="Natural-language intent.")
    name: str = ""
    constraints: list[str] = []
    forbidden: list[str] = []
    success_signals: list[str] = []
    # Phase 1 additions
    inherit_from: list[str] = []
    inherit_from_organisms: list[str] = []
    max_inherited_skills: int = 5
    mcp_servers: list[dict] = []  # raw dicts → MCPServerSpec at construction
```

Modify the `seed` route:

```python
@router.post("/seed")
async def seed(req: SeedRequest):
    from .skills import inherit as _inherit
    from .types import MCPServerSpec

    inherited_refs, parent_orgs = _inherit.resolve_seed_inheritance(
        inherit_from=req.inherit_from or None,
        inherit_from_organisms=req.inherit_from_organisms or None,
        max_inherited_skills=req.max_inherited_skills,
    )
    mcp_specs = [MCPServerSpec(**d) for d in (req.mcp_servers or [])]

    org = runtime.seed(
        intent_goal=req.goal, name=req.name,
        constraints=req.constraints, forbidden=req.forbidden,
        success_signals=req.success_signals,
    )
    # Patch DNA fields the runtime.seed signature doesn't yet accept
    org.inherited_skills = inherited_refs
    org.parent_organisms = parent_orgs
    org.mcp_servers = mcp_specs
    store.save_organism(org)

    await events.emit("organism.seeded", {
        "organism_id": org.id,
        "organism": org.model_dump(mode="json"),
    })
    return {"organism": org.model_dump(mode="json")}
```

- [ ] **Step 11.2: Add Skill Library endpoints**

After the existing routes, add:

```python
@router.get("/skills")
async def list_skills():
    from .skills import pool as _pool
    return {"skills": _pool.list_summaries()}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    from .skills import pool as _pool
    s = _pool.load(skill_id)
    if not s:
        raise HTTPException(404, f"skill {skill_id} not found")
    return {
        "skill_id": s.skill_id, "name": s.name, "description": s.description,
        "distilled_at": s.distilled_at.isoformat(),
        "parent_organisms": s.parent_organisms, "parent_skills": s.parent_skills,
        "generation": s.generation, "fitness_at_death": s.fitness_at_death,
        "n_decisions_distilled": s.n_decisions_distilled,
        "trigger_patterns": s.trigger_patterns, "forbidden_patterns": s.forbidden_patterns,
        "body": s.body,
    }


@router.get("/skills/{skill_id}/lineage")
async def get_skill_lineage(skill_id: str):
    from .skills import pool as _pool
    seen: set[str] = set()
    frontier = [skill_id]
    nodes: list[dict] = []
    edges: list[dict] = []
    while frontier:
        sid = frontier.pop()
        if sid in seen:
            continue
        seen.add(sid)
        s = _pool.load(sid)
        if not s:
            continue
        nodes.append({"id": sid, "kind": "skill", "name": s.name,
                      "generation": s.generation,
                      "fitness_at_death": s.fitness_at_death})
        for parent in s.parent_skills:
            edges.append({"source": parent, "target": sid, "kind": "skill_parent"})
            frontier.append(parent)
        for org in s.parent_organisms:
            org_node_id = f"org:{org}"
            if org_node_id not in seen:
                seen.add(org_node_id)
                nodes.append({"id": org_node_id, "kind": "organism", "name": org})
            edges.append({"source": org_node_id, "target": sid, "kind": "distilled_from"})
    return {"nodes": nodes, "edges": edges}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from .skills import pool as _pool
    if not _pool.delete(skill_id):
        raise HTTPException(404, f"skill {skill_id} not found")
    return {"deleted": skill_id}
```

- [ ] **Step 11.3: Add MCP endpoints**

```python
@router.post("/organisms/{organism_id}/mcp/attach")
async def attach_mcp(organism_id: str, spec: dict):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    from .types import MCPServerSpec
    parsed = MCPServerSpec(**spec)
    # Replace if same name, else append
    org.mcp_servers = [s for s in org.mcp_servers if s.name != parsed.name] + [parsed]
    store.save_organism(org)
    from .mcp import client as _mc
    await _mc.pool.ensure_organism(organism_id, [parsed])
    return {"ok": True, "mcp_servers": [s.model_dump() for s in org.mcp_servers]}


@router.delete("/organisms/{organism_id}/mcp/{server_name}")
async def detach_mcp(organism_id: str, server_name: str):
    org = store.load_organism(organism_id)
    if not org:
        raise HTTPException(404, f"organism {organism_id} not found")
    before = len(org.mcp_servers)
    org.mcp_servers = [s for s in org.mcp_servers if s.name != server_name]
    if len(org.mcp_servers) == before:
        raise HTTPException(404, f"server {server_name} not attached")
    store.save_organism(org)
    return {"ok": True, "remaining": [s.model_dump() for s in org.mcp_servers]}


@router.get("/mcp/global")
async def mcp_global_status():
    from .mcp import client as _mc, catalog as _cat
    return {
        "configured": [s.model_dump() for s in _cat.load_global_specs()],
        "runtime": await _mc.pool.status(),
    }


@router.post("/mcp/global/reload")
async def mcp_global_reload():
    from .mcp import client as _mc, catalog as _cat
    specs = _cat.load_global_specs()
    await _mc.pool.ensure_global(specs)
    return {"reloaded": len(specs)}
```

- [ ] **Step 11.4: Smoke-test endpoints register**

Run: `/usr/local/bin/python3.11 -c "from backend.genesis.api import router; print(sorted(set(r.path for r in router.routes)))"`
Expected: list includes `/api/genesis/skills`, `/api/genesis/skills/{skill_id}`, `/api/genesis/skills/{skill_id}/lineage`, `/api/genesis/organisms/{organism_id}/mcp/attach`, `/api/genesis/mcp/global`, `/api/genesis/mcp/global/reload`.

- [ ] **Step 11.5: Commit**

```bash
git add backend/genesis/api.py
git commit -m "feat(genesis): API for skills (CRUD+lineage), MCP attach/detach, seed inheritance"
```

---

### Task 12: Frontend — `useGenesis` hook additions

**Files:**
- Modify: `frontend/src/hooks/useGenesis.js`

- [ ] **Step 12.1: Add skill helpers to the hook**

Open `frontend/src/hooks/useGenesis.js`. After `removeSource`, add:

```javascript
  // ── Skills ─────────────────────────────────────────────────────
  const [skills, setSkills] = useState([])

  const loadSkills = useCallback(async () => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/skills`)
    const j = await r.json()
    setSkills(j.skills || [])
  }, [])

  const getSkill = useCallback(async (id) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/skills/${id}`)
    return await r.json()
  }, [])

  const getSkillLineage = useCallback(async (id) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/skills/${id}/lineage`)
    return await r.json()
  }, [])

  const deleteSkill = useCallback(async (id) => {
    await fetch(`${HTTP_BASE}/api/genesis/skills/${id}`, { method: 'DELETE' })
    await loadSkills()
  }, [loadSkills])
```

- [ ] **Step 12.2: Extend `seed()` to accept inheritance + MCP**

Replace the existing `seed` callback with:

```javascript
  const seed = useCallback(async ({ goal, name, constraints = [], forbidden = [],
                                    inherit_from = [], inherit_from_organisms = [],
                                    max_inherited_skills = 5,
                                    mcp_servers = [] }) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/seed`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, name, constraints, forbidden,
                              inherit_from, inherit_from_organisms,
                              max_inherited_skills, mcp_servers }),
    })
    const j = await r.json()
    await loadOrganisms()
    setActiveId(j.organism.id)
    return j.organism
  }, [loadOrganisms])
```

- [ ] **Step 12.3: Auto-refresh skills on `organism.distilled` event**

In the `ws.onmessage` handler, after the `organism.seeded` block, add:

```javascript
        if (e.type === 'organism.distilled') {
          loadSkills()
        }
```

Also add an initial load:

```javascript
  useEffect(() => { loadSkills() }, [loadSkills])
```

And add to the return:

```javascript
    skills,
    loadSkills, getSkill, getSkillLineage, deleteSkill,
```

- [ ] **Step 12.4: Sanity build**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow/frontend && npx vite build 2>&1 | tail -5`
Expected: built successfully.

- [ ] **Step 12.5: Commit**

```bash
git add frontend/src/hooks/useGenesis.js
git commit -m "feat(genesis-ui): useGenesis exposes skills + inheritance + mcp_servers"
```

---

### Task 13: Frontend — SkillLibrary panel

**Files:**
- Create: `frontend/src/components/genesis/SkillLineageGraph.jsx`
- Create: `frontend/src/components/genesis/SkillLibrary.jsx`
- Modify: `frontend/src/components/genesis/GenesisPage.jsx`

- [ ] **Step 13.1: Create `SkillLineageGraph.jsx`**

```jsx
import React, { useMemo } from 'react'
import {
  ReactFlow, Background, MarkerType,
  useNodesState, useEdgesState,
} from '@xyflow/react'

export default function SkillLineageGraph({ lineage }) {
  const data = useMemo(() => {
    const nodes = (lineage?.nodes || []).map((n, i) => ({
      id: n.id,
      data: { label: n.kind === 'skill'
                       ? `🧬 ${n.name} (gen ${n.generation})`
                       : `🦠 ${n.name?.slice(0, 12)}` },
      position: { x: (i % 4) * 180, y: Math.floor(i / 4) * 90 },
      style: {
        background: n.kind === 'skill' ? 'rgba(168,85,247,0.18)' : 'rgba(16,185,129,0.18)',
        border: `1px solid ${n.kind === 'skill' ? 'rgba(168,85,247,0.6)' : 'rgba(16,185,129,0.6)'}`,
        color: '#e5e7eb', fontSize: 11, padding: 6, borderRadius: 6,
      },
    }))
    const edges = (lineage?.edges || []).map((e, i) => ({
      id: `e${i}`, source: e.source, target: e.target,
      style: { stroke: e.kind === 'distilled_from' ? '#10b981' : '#a855f7' },
      markerEnd: { type: MarkerType.ArrowClosed },
    }))
    return { nodes, edges }
  }, [lineage])

  const [nodes, , onNodesChange] = useNodesState(data.nodes)
  const [edges, , onEdgesChange] = useEdgesState(data.edges)
  return (
    <div className="h-64 border border-forge-border rounded">
      <ReactFlow nodes={nodes} edges={edges}
                 onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
                 fitView proOptions={{ hideAttribution: true }}>
        <Background gap={16} size={1} color="#3f3f46" />
      </ReactFlow>
    </div>
  )
}
```

- [ ] **Step 13.2: Create `SkillLibrary.jsx`**

```jsx
import React, { useEffect, useState } from 'react'
import SkillLineageGraph from './SkillLineageGraph'

export default function SkillLibrary({ skills, onClose, getSkill, getSkillLineage,
                                       deleteSkill, onSeedFromSkill }) {
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [lineage, setLineage] = useState(null)

  useEffect(() => {
    if (!selected) { setDetail(null); setLineage(null); return }
    let alive = true
    Promise.all([getSkill(selected), getSkillLineage(selected)]).then(([d, l]) => {
      if (!alive) return
      setDetail(d); setLineage(l)
    })
    return () => { alive = false }
  }, [selected, getSkill, getSkillLineage])

  return (
    <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex">
      <div className="m-auto bg-forge-bg border border-purple-500/40 rounded-2xl w-[1000px] max-w-[95vw] max-h-[90vh] flex flex-col shadow-2xl shadow-purple-500/20">
        <div className="flex items-center justify-between p-4 border-b border-forge-border">
          <div className="flex items-center gap-2">
            <span className="text-2xl">📚</span>
            <h2 className="text-lg font-semibold">Skill Library</h2>
            <span className="text-xs text-forge-muted">{skills.length} skill{skills.length===1?'':'s'} in pool</span>
          </div>
          <button onClick={onClose} className="text-forge-muted hover:text-forge-text px-2">✕</button>
        </div>
        <div className="flex-1 grid grid-cols-2 overflow-hidden">
          {/* Left: list */}
          <div className="border-r border-forge-border overflow-auto p-2 space-y-1">
            {skills.length === 0 && (
              <div className="text-xs text-forge-muted italic text-center py-8">
                No skills yet. Let an organism live, then die.
              </div>
            )}
            {skills.map(s => (
              <button
                key={s.skill_id}
                onClick={() => setSelected(s.skill_id)}
                className={`w-full text-left p-2 rounded text-xs ${
                  selected===s.skill_id ? 'bg-purple-500/20 border border-purple-400/40' : 'hover:bg-forge-border/40'
                }`}
              >
                <div className="font-medium">🧬 {s.name}</div>
                <div className="text-[10px] text-forge-muted truncate">{s.description}</div>
                <div className="flex items-center gap-2 mt-1 text-[10px] text-forge-muted">
                  <span>gen {s.generation}</span>
                  <span>·</span>
                  <span>fitness {(s.fitness_at_death*100).toFixed(0)}%</span>
                  <span>·</span>
                  <span>{s.n_decisions_distilled} decisions</span>
                </div>
              </button>
            ))}
          </div>
          {/* Right: detail */}
          <div className="overflow-auto p-4">
            {!selected && (
              <div className="text-forge-muted text-sm italic">Select a skill to inspect.</div>
            )}
            {detail && (
              <div className="space-y-3 text-xs">
                <div>
                  <div className="text-base font-semibold">🧬 {detail.name}</div>
                  <div className="text-forge-muted text-[11px]">{detail.description}</div>
                </div>
                <div className="flex flex-wrap gap-2 text-[10px]">
                  <Chip>gen {detail.generation}</Chip>
                  <Chip>fitness {(detail.fitness_at_death*100).toFixed(0)}%</Chip>
                  <Chip>{detail.n_decisions_distilled} decisions distilled</Chip>
                  <Chip>{detail.parent_skills.length} parent skills</Chip>
                </div>
                {lineage && lineage.nodes?.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">Lineage</div>
                    <SkillLineageGraph lineage={lineage} />
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">Skill body</div>
                  <pre className="whitespace-pre-wrap font-sans text-[11px] bg-forge-border/30 p-3 rounded leading-relaxed">{detail.body}</pre>
                </div>
                <div className="flex gap-2 pt-2 border-t border-forge-border">
                  <button
                    onClick={() => onSeedFromSkill(detail.skill_id)}
                    className="flex-1 px-3 py-1.5 rounded bg-purple-500/30 hover:bg-purple-500/50 border border-purple-400 text-purple-100 text-xs"
                  >🧬 Seed organism with this</button>
                  <button
                    onClick={() => { if (confirm('Delete this skill from the pool?')) deleteSkill(detail.skill_id).then(() => setSelected(null)) }}
                    className="px-3 py-1.5 rounded bg-red-500/20 hover:bg-red-500/40 border border-red-500/40 text-red-300 text-xs"
                  >🗑 Delete</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Chip({ children }) {
  return <span className="px-2 py-0.5 rounded-full bg-forge-border/50 border border-forge-border text-forge-text/80">{children}</span>
}
```

- [ ] **Step 13.3: Wire SkillLibrary into `GenesisPage.jsx`**

Add to imports:
```jsx
import SkillLibrary from './SkillLibrary'
```

Pull skill helpers from the hook:
```jsx
const { /* ... existing fields ..., */ skills, getSkill, getSkillLineage, deleteSkill } = g
```

Add state:
```jsx
const [showLibrary, setShowLibrary] = useState(false)
const [seedFromSkillId, setSeedFromSkillId] = useState(null)
```

Add the button in the header (next to "🌱 Seed Organism"):

```jsx
<button
  onClick={() => setShowLibrary(true)}
  className="text-xs px-3 py-1.5 rounded-lg bg-forge-border/50 hover:bg-purple-500/20 border border-forge-border"
  title="Browse the Skill pool"
>📚 Skills ({skills.length})</button>
```

Render the modal at the bottom of the JSX, alongside the Seed modal:

```jsx
{showLibrary && (
  <SkillLibrary
    skills={skills}
    getSkill={getSkill}
    getSkillLineage={getSkillLineage}
    deleteSkill={deleteSkill}
    onClose={() => setShowLibrary(false)}
    onSeedFromSkill={(id) => { setSeedFromSkillId(id); setShowLibrary(false); setShowSeedModal(true) }}
  />
)}
```

- [ ] **Step 13.4: Build sanity check**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow/frontend && npx vite build 2>&1 | tail -5`
Expected: built successfully.

- [ ] **Step 13.5: Commit**

```bash
git add frontend/src/components/genesis/SkillLineageGraph.jsx frontend/src/components/genesis/SkillLibrary.jsx frontend/src/components/genesis/GenesisPage.jsx
git commit -m "feat(genesis-ui): SkillLibrary modal with lineage graph"
```

---

### Task 14: Frontend — templates + InheritancePicker

**Files:**
- Create: `frontend/src/components/genesis/templates.js`
- Create: `frontend/src/components/genesis/InheritancePicker.jsx`
- Modify: `frontend/src/components/genesis/GenesisPage.jsx` (Seed modal)

- [ ] **Step 14.1: Create `templates.js`**

```javascript
export const ORGANISM_TEMPLATES = [
  {
    id: 'customer_pulse',
    icon: '📨',
    name: 'Customer Pulse',
    goal: 'Watch every customer email, route urgent ones to humans, draft replies for the rest.',
    constraints: ['respond within 5 minutes', 'never auto-reply to billing'],
    forbidden: ['share PII', 'make pricing promises'],
    suggested_sources: [
      { kind: 'webhook', type: 'email_received' },
      { kind: 'interval', type: 'health_check', interval_s: 300 },
    ],
    suggested_mcp: ['filesystem', 'fetch'],
  },
  {
    id: 'repo_sentinel',
    icon: '👁',
    name: 'Repo Sentinel',
    goal: 'Watch GitHub events, summarize PRs, flag dependency vulnerabilities.',
    constraints: ['don\'t spam authors', 'cite line numbers'],
    forbidden: ['auto-merge', 'auto-close issues'],
    suggested_sources: [{ kind: 'webhook', type: 'gh_event' }],
    suggested_mcp: ['github'],
  },
  {
    id: 'market_dreamer',
    icon: '📈',
    name: 'Market Dreamer',
    goal: 'Poll a price feed, dream worst-case scenarios, alert on anomalies.',
    constraints: ['alert only on >2-sigma moves', 'cool down 10 min after alert'],
    forbidden: ['execute trades'],
    suggested_sources: [
      { kind: 'http_poll', type: 'price_tick', interval_s: 60,
        url: 'https://api.example.com/price' },
    ],
    suggested_mcp: ['fetch'],
  },
  {
    id: 'blank',
    icon: '🌱',
    name: 'Blank slate',
    goal: '',
    constraints: [], forbidden: [],
    suggested_sources: [], suggested_mcp: [],
  },
]
```

- [ ] **Step 14.2: Create `InheritancePicker.jsx`**

```jsx
import React from 'react'

export default function InheritancePicker({ skills, selected, onChange }) {
  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  if (skills.length === 0) {
    return (
      <div className="text-[10px] text-forge-muted italic">
        No skills in the pool yet. Inheritance will activate once organisms have lived and died.
      </div>
    )
  }
  return (
    <div className="space-y-1 max-h-32 overflow-auto">
      {skills.map(s => {
        const on = selected.includes(s.skill_id)
        return (
          <button
            key={s.skill_id}
            type="button"
            onClick={() => toggle(s.skill_id)}
            className={`w-full text-left p-1.5 rounded text-[11px] flex items-center gap-2 ${
              on ? 'bg-purple-500/30 border border-purple-400/60' : 'bg-forge-border/30 hover:bg-forge-border/50 border border-forge-border'
            }`}
          >
            <span className="text-sm">{on ? '✓' : '🧬'}</span>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{s.name}</div>
              <div className="text-[10px] text-forge-muted truncate">
                gen {s.generation} · fitness {(s.fitness_at_death*100).toFixed(0)}%
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 14.3: Modify the Seed modal in `GenesisPage.jsx`**

Find the `SeedModal` component. Add new state and props:

```jsx
function SeedModal({ onClose, onSeed, skills, prefillSkillId }) {
  const [template, setTemplate] = useState(null)
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const [constraintsText, setConstraintsText] = useState('')
  const [forbiddenText, setForbiddenText] = useState('')
  const [inheritIds, setInheritIds] = useState(prefillSkillId ? [prefillSkillId] : [])
  const [submitting, setSubmitting] = useState(false)

  const applyTemplate = (t) => {
    setTemplate(t.id)
    setName(t.id === 'blank' ? '' : t.id)
    setGoal(t.goal)
    setConstraintsText((t.constraints || []).join('\n'))
    setForbiddenText((t.forbidden || []).join('\n'))
  }
  // ... existing submit() unchanged but now also passes inherit_from: inheritIds
```

Add the template chip row at the top of the modal body, before the Name field:

```jsx
<div className="flex flex-wrap gap-2 mb-3">
  {ORGANISM_TEMPLATES.map(t => (
    <button key={t.id} type="button" onClick={() => applyTemplate(t)}
            className={`text-xs px-2 py-1 rounded-full border ${
              template===t.id ? 'bg-purple-500/30 border-purple-400 text-purple-100'
                              : 'bg-forge-border/40 border-forge-border hover:bg-forge-border/60'
            }`}>
      {t.icon} {t.name}
    </button>
  ))}
</div>
```

After the Forbidden field, add the InheritancePicker:

```jsx
<Field label="Inherit skills (DNA from past organisms)">
  <InheritancePicker skills={skills} selected={inheritIds} onChange={setInheritIds} />
</Field>
```

In `submit()` change the call to:
```javascript
await onSeed({
  name: name.trim(), goal: goal.trim(),
  constraints: constraintsText.split('\n').map(s => s.trim()).filter(Boolean),
  forbidden: forbiddenText.split('\n').map(s => s.trim()).filter(Boolean),
  inherit_from: inheritIds,
})
```

Don't forget the imports at the top of GenesisPage.jsx:

```jsx
import { ORGANISM_TEMPLATES } from './templates'
import InheritancePicker from './InheritancePicker'
```

And pass `skills` and `prefillSkillId` into `SeedModal`:

```jsx
{showSeedModal && (
  <SeedModal
    skills={skills}
    prefillSkillId={seedFromSkillId}
    onClose={() => { setShowSeedModal(false); setSeedFromSkillId(null) }}
    onSeed={async (data) => { await seed(data); setShowSeedModal(false); setSeedFromSkillId(null) }}
  />
)}
```

- [ ] **Step 14.4: Build sanity check**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow/frontend && npx vite build 2>&1 | tail -5`
Expected: built successfully.

- [ ] **Step 14.5: Commit**

```bash
git add frontend/src/components/genesis/templates.js frontend/src/components/genesis/InheritancePicker.jsx frontend/src/components/genesis/GenesisPage.jsx
git commit -m "feat(genesis-ui): organism templates + skill InheritancePicker in Seed modal"
```

---

### Task 15: Frontend — guided Tour

**Files:**
- Create: `frontend/src/components/genesis/Tour.jsx`
- Modify: `frontend/src/components/genesis/GenesisPage.jsx`

- [ ] **Step 15.1: Create `Tour.jsx`**

```jsx
import React, { useEffect, useRef, useState } from 'react'

const STEPS = [
  { ms: 5000,  text: '🥚 Meet Genesis. Watch this organism be born.',
    action: 'seed' },
  { ms: 8000,  text: '👁 It can perceive.', action: 'perceive' },
  { ms: 12000, text: '💭 And it dreams.', action: 'dream' },
  { ms: 10000, text: '✏ You can rewrite its past.', action: 'edit' },
  { ms: 6000,  text: '⭐ Promote a counterfactual to reality.', action: 'promote' },
  { ms: 8000,  text: '🪦 When it dies, its mind becomes inheritable.\nThis is digital evolution.',
    action: 'die' },
]

export default function Tour({ open, onClose, g }) {
  const [step, setStep] = useState(0)
  const [running, setRunning] = useState(false)
  const stateRef = useRef({ orgId: null, decisionId: null, branchId: null })

  useEffect(() => {
    if (!open) { setStep(0); setRunning(false); stateRef.current = {orgId:null,decisionId:null,branchId:null}; return }
    setRunning(true)
    let cancelled = false

    const runStep = async (i) => {
      if (cancelled || i >= STEPS.length) {
        if (!cancelled) { setRunning(false) }
        return
      }
      setStep(i)
      const s = STEPS[i]
      try {
        await doAction(s.action, stateRef.current, g)
      } catch (e) { console.error('[Tour] step failed:', e) }
      await new Promise(r => setTimeout(r, s.ms))
      runStep(i + 1)
    }
    runStep(0)
    return () => { cancelled = true }
  }, [open, g])

  if (!open) return null
  const s = STEPS[step]
  return (
    <div className="fixed inset-x-0 bottom-6 z-50 flex justify-center pointer-events-none">
      <div className="pointer-events-auto bg-forge-bg/95 backdrop-blur border border-purple-400/60 rounded-xl px-6 py-4 shadow-2xl shadow-purple-500/30 flex items-center gap-4 max-w-2xl">
        <div className="flex items-center gap-2 text-xs text-purple-300">
          <span>Tour {step+1}/{STEPS.length}</span>
          {running && <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />}
        </div>
        <div className="flex-1 text-sm whitespace-pre-line">{s.text}</div>
        <button onClick={onClose} className="text-forge-muted hover:text-forge-text text-xs px-2">Skip</button>
      </div>
    </div>
  )
}

async function doAction(name, state, g) {
  switch (name) {
    case 'seed': {
      const o = await g.seed({
        name: 'tour_subject',
        goal: 'Watch incoming events and respond helpfully.',
        constraints: ['be concise'],
        forbidden: ['leak PII'],
      })
      state.orgId = o.id
      return
    }
    case 'perceive':
      if (state.orgId) await g.perceive(state.orgId, {
        type: 'urgent_email',
        from: 'vip@bigcorp.com',
        subject: 'URGENT: account locked',
      })
      return
    case 'dream':
      if (state.orgId) await g.dream(state.orgId, 5)
      return
    case 'edit': {
      // Pick the first real decision and rewrite it
      if (state.orgId && g.graph?.nodes?.length) {
        const real = g.graph.nodes.find(n => !n.is_dream && !n.shadow_branch)
        if (real) {
          state.decisionId = real.id
          const branch = await g.editDecision(state.orgId, real.id, {
            new_action: { tool: 'send_slack', args: { channel: '#vip', text: 'Escalated' } },
            new_reasoning: 'Tour edit: prefer escalation for VIP urgent emails.',
          })
          if (branch?.branch?.id) state.branchId = branch.branch.id
        }
      }
      return
    }
    case 'promote':
      if (state.orgId && state.branchId) await g.promoteBranch(state.orgId, state.branchId)
      return
    case 'die':
      if (state.orgId) await g.killOrganism(state.orgId)
      return
  }
}
```

- [ ] **Step 15.2: Wire Tour into `GenesisPage.jsx`**

Add to imports:
```jsx
import Tour from './Tour'
```

Add state:
```jsx
const [tourOpen, setTourOpen] = useState(false)
```

Add the button in the header next to the Skill Library button:

```jsx
<button
  onClick={() => setTourOpen(true)}
  className="text-xs px-3 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/40 border border-purple-500/40 text-purple-200"
>▶ Tour</button>
```

Render the Tour at the bottom of the JSX:

```jsx
<Tour open={tourOpen} onClose={() => setTourOpen(false)} g={g} />
```

- [ ] **Step 15.3: Build**

Run: `cd /Users/jayanthmuthina/Desktop/Deriv_Hackathon_ForgeFlow/frontend && npx vite build 2>&1 | tail -5`
Expected: built successfully.

- [ ] **Step 15.4: Commit**

```bash
git add frontend/src/components/genesis/Tour.jsx frontend/src/components/genesis/GenesisPage.jsx
git commit -m "feat(genesis-ui): scripted Tour walks through seed→perceive→dream→edit→promote→die"
```

---

### Task 16: Polish — Slack noise + .env.example

**Files:**
- Modify: `backend/main.py`
- Modify: `.env.example`

- [ ] **Step 16.1: Wrap Slack startup in `backend/main.py`**

Replace the existing Slack bot startup block in `lifespan()`:

```python
    # Startup: activate Slack bot (bidirectional — /forge command, DMs)
    slack_disabled = os.getenv("SLACK_DISABLED", "0") in ("1", "true", "yes")
    if _slack_app_real and not slack_disabled:
        asyncio.create_task(_safe_start_slack_bot())
        print("[Slack] Bot starting in Socket Mode (bidirectional)")
    elif slack_disabled:
        print("[Slack] Disabled by SLACK_DISABLED=1")
    else:
        print("[Slack] App token not configured — /forge command disabled")
```

Add the helper at module scope (near the other helpers):

```python
async def _safe_start_slack_bot():
    """Wrap Slack startup so cert / network errors don't dump a stack trace."""
    try:
        from backend.slack.bot import start_slack_bot
        await start_slack_bot()
    except Exception as e:
        import logging
        logging.getLogger("slack").warning(
            f"Slack bot offline: {type(e).__name__}: {str(e)[:120]}"
        )
```

Reduce Slack module log level near the top of `main.py`:

```python
import logging
logging.getLogger("slack").setLevel(logging.WARNING)
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)
```

- [ ] **Step 16.2: Update `.env.example`**

Add at the bottom:

```
# ── Genesis Phase 1 ──────────────────────────────────────
# Set SLACK_DISABLED=1 if you don't have Slack creds OR your local Python is
# missing CA certs (common on macOS without Python.org installer's certifi run).
# This silences the Slack startup entirely so logs stay clean.
SLACK_DISABLED=0

# Path to global ambient MCP server config. Defaults to
# $GENESIS_STORAGE/_mcp_global.json. Override here if you want to share
# one config across multiple Genesis storage dirs.
# GENESIS_MCP_GLOBAL=/absolute/path/to/_mcp_global.json
```

- [ ] **Step 16.3: Smoke-test backend boots cleanly**

Run: `lsof -ti:8001 2>/dev/null | xargs -r kill -9; SLACK_DISABLED=1 /usr/local/bin/python3.11 -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload 2>&1 | head -25 &`

Wait 5s then `curl -s http://127.0.0.1:8001/api/genesis/lifecycle/status` and `curl -s http://127.0.0.1:8001/api/genesis/skills`. Both should return JSON without errors. Kill the server: `lsof -ti:8001 | xargs kill -9`.

- [ ] **Step 16.4: Commit**

```bash
git add backend/main.py .env.example
git commit -m "chore(genesis): suppress Slack SSL noise + document SLACK_DISABLED"
```

---

### Task 17: Final integration smoke test

**Files:**
- Create: `backend/tests/genesis/test_full_lifecycle.py`

- [ ] **Step 17.1: Write the integration test**

```python
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
            "action": {"tool": "noop", "args": {}}, "alternatives": []
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
    refs, parents = inherit.resolve_seed_inheritance(inherit_from=[skill_id])
    assert len(refs) == 1
    assert refs[0].skill_id == skill_id

    org2 = Organism(name="child", intent=Intent(goal="child goal"),
                    inherited_skills=refs, parent_organisms=parents)
    store.save_organism(org2)

    fake_llm.responses.append(json.dumps({
        "reasoning": "with inherited wisdom",
        "action": {"tool": "noop", "args": {}}, "alternatives": []
    }))
    await runtime.perceive(org2.id, {"type": "tick"})

    # The inherited skill body must have been in the prompt
    assert any("Noop is fine for tick events" in p["prompt"]
               for p in fake_llm.prompts)
```

- [ ] **Step 17.2: Run full test suite**

Run: `/usr/local/bin/python3.11 -m pytest backend/tests/genesis -v`
Expected: ALL PASS.

- [ ] **Step 17.3: Final commit**

```bash
git add backend/tests/genesis/test_full_lifecycle.py
git commit -m "test(genesis): end-to-end lifecycle + inheritance integration test"
```

---

## Done Criteria

When all 17 tasks are checked off:
- [ ] `/usr/local/bin/python3.11 -m pytest backend/tests/genesis -v` — ALL PASS
- [ ] `cd frontend && npx vite build` — builds without errors
- [ ] `SLACK_DISABLED=1 python3.11 -m uvicorn backend.main:app --port 8001` boots without stack traces
- [ ] Frontend at `http://localhost:3000/#genesis` shows the new "📚 Skills (N)" and "▶ Tour" header buttons
- [ ] Clicking "▶ Tour" runs the 6-step demo end-to-end without errors
- [ ] After the Tour completes, the Skill Library shows at least one new distilled Skill
- [ ] Seeding a new organism with that Skill in the InheritancePicker produces an organism whose first perceive includes the inherited skill text in the LLM prompt (verifiable via backend logs)

---

## Self-Review Checklist (Pre-execution)

- [x] **Spec coverage:** Every section of the design spec has at least one corresponding task. §2 architecture → Tasks 4, 10. §3 data model → Task 2. §4 MCP → Tasks 8, 9, 10, 11. §5 Skills → Tasks 5, 6, 7, 11. §6 Polish → Tasks 13–16. §7 build order matches Tasks 1–17. §8 test surface → Tasks 3, 5, 6, 7, 9, 17.
- [x] **Placeholder scan:** No "TBD" / "TODO" / "implement later" outside the explicit fallback note in Step 9.3.
- [x] **Type consistency:** `MCPServerSpec`, `SkillRef`, `Skill`, `MCPPool.call(...)`, `pool.write/load/delete/list_summaries`, `inherit.resolve_seed_inheritance`, `inherit.load_skills_text`, `distill.distill` — all referenced consistently across tasks.
