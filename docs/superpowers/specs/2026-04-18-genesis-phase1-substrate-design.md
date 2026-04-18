# Genesis Phase 1 — Substrate (MCP + Skills + Polish)

**Status:** approved (sections 1–4) — ready for implementation planning
**Date:** 2026-04-18
**Author:** ForgeFlow / Genesis team
**Phase context:** Phase 1 of 4. Phases 2–4 (Society / Evolution / Embodiment) are out of scope here and get their own specs after Phase 1 ships.

---

## 1. Problem & Goals

Genesis (the post-LangGraph "living digital organism" runtime) currently has:

- An uncompiled Intent Core, perception, dreaming, causal-graph editing, counterfactual branches, and a continuous perception loop.
- A hardcoded set of four built-in tools: `send_slack`, `http_request`, `remember`, `declare_done`.
- No mechanism for organisms to acquire new capabilities, no way for them to inherit knowledge from past organisms, and no path to compose with the wider Claude/MCP ecosystem.

The judge critique that motivates this phase: "no MCP, no Skills, no novel architecture." Phase 1 directly answers MCP and Skills, and lays the substrate that Phases 2–4 (Society, Evolution, Embodiment) will build on.

### Goals

1. **MCP nervous system.** Any organism can call any MCP tool from a curated global server pool, AND can declare its own private MCP servers in its DNA.
2. **Skills as inheritable DNA.** When an organism dies, its decisions distill into a Skill file in a Genesis-internal pool. New organisms can be seeded with explicit Skill inheritance; the inherited Skills load into context at every perception.
3. **Polish.** One-click organism templates, a guided "Tour" that demonstrates the full Genesis story end-to-end, a Skill Library UI, and the elimination of unrelated noise (Slack SSL crashes) from local dev.

### Non-goals (deferred)

- Real fitness function (placeholder heuristic only — Phase 3 owns this).
- Skill mutation / crossover (Phase 3).
- Inter-organism event subscription / negotiation protocol (Phase 2).
- LoRA / WASM / compiled-Python substrates (Phase 4).
- Skill versioning. Each distillation is a fresh `skill_id`; no semver.
- Skill conflict resolution between inherited Skills — the LLM resolves implicitly via the prompt.
- Publishing distilled Skills to the global `~/.claude/skills/` directory. Genesis pool stays internal (per Q2=b).

---

## 2. Architecture

### 2.1 Approach

**Approach B — Perception Pipeline** was selected (over "Bolt-on" and "Capability Registry"). The current `runtime.perceive()` function is refactored into a 5-stage pipeline. Each stage is a pure async function with a clear contract; new capabilities (MCP tools, Skills, future negotiation messages, future fitness updates) plug into specific stages without bloating `runtime.py` further.

The pipeline:

```
perception arrives
  ↓
[1] gather_context     → load organism, recent decisions, inherited skills text,
                         (future Phase 2: peer organism messages)
  ↓
[2] load_capabilities  → resolve global ∪ private MCP servers, discover their tools,
                         merge with built-in tools — produces a unified tool catalog
  ↓
[3] reason             → LLM call with: intent + context + skills + tool catalog
  ↓
[4] act                → dispatch tool call; built-in tools execute inline,
                         mcp__server__tool tools route to MCPPool
  ↓
[5] record             → save Decision, emit events, update fitness placeholder,
                         (future Phase 3: real fitness update)
```

### 2.2 New module layout

```
backend/genesis/
  pipeline/
    __init__.py
    stages.py          # the 5 pipeline stages
  mcp/
    __init__.py
    client.py          # MCPPool — connection pool + dispatch
    catalog.py         # global ambient server config loader
  skills/
    __init__.py
    pool.py            # read/write organisms/_skill_pool/*.md
    distill.py         # LLM call: organism's decisions → Skill markdown+frontmatter
    inherit.py         # at seed time, attach SkillRefs to the new organism
```

Existing modules touched: `types.py` (new fields), `runtime.py` (replaced internals; same external contract for `perceive`/`seed`), `api.py` (new endpoints), `lifecycle.py` (call `distill` before organism teardown).

### 2.3 Storage layout

```
organisms/
  _skill_pool/                # NEW — Genesis-internal pool (Q2=b)
    sk_<hash>.md              # YAML frontmatter + markdown body (Q3=c)
  _mcp_global.json            # NEW — operator-curated ambient servers
  o_<id>/
    organism.json             # now includes mcp_servers, inherited_skills,
                              #                fitness_score, parent_organisms,
                              #                distilled_skill_id
    decisions/...
    branches/...
```

---

## 3. Data Model

New types in `backend/genesis/types.py`:

```python
class MCPServerSpec(BaseModel):
    name: str                                 # "filesystem", "github", etc.
    command: str                              # "npx", "python", "uvx", ...
    args: list[str] = []
    env: dict[str, str] = {}
    transport: str = "stdio"                  # "stdio" | "sse"

class SkillRef(BaseModel):
    """Pointer into the skill pool. Lives in organism DNA."""
    skill_id: str
    name: str                                 # cached for fast display
    inherited_at: datetime
```

Extensions to `Organism`:

```python
class Organism(BaseModel):
    # ... existing fields ...
    mcp_servers: list[MCPServerSpec] = []     # private MCP servers (Q1=c)
    inherited_skills: list[SkillRef] = []     # DNA from ancestors
    parent_organisms: list[str] = []          # lineage chain (organism IDs)
    fitness_score: float = 0.0                # placeholder; Phase 3 will own this
    distilled_skill_id: Optional[str] = None  # set on death → resulting skill ID
```

The pool Skill file format (`organisms/_skill_pool/sk_<hash>.md`):

```markdown
---
skill_id: sk_a1b2c3d4
name: customer_email_triage
description: Routes customer emails by urgency, escalates billing issues to humans
distilled_at: 2026-04-18T14:23:11Z
parent_organisms: [o_xxx, o_yyy]
parent_skills: [sk_e5f6, sk_g7h8]
generation: 3
fitness_at_death: 0.78
n_decisions_distilled: 47
trigger_patterns:
  - "incoming_email with subject contains 'urgent'"
  - "incoming_email from VIP domain"
forbidden_patterns:
  - "auto-reply to billing inquiries — always escalate"
---

# What this skill knows
[LLM-written narrative]

# What worked
[LLM-written narrative]

# What failed
[LLM-written narrative]

# Patterns observed
[LLM-written narrative]
```

The frontmatter is the **structured** part (filterable, machine-readable for inheritance/lineage). The markdown body is **LLM-written narrative guidance** that the next organism's reasoning step reads as context.

---

## 4. MCP Nervous System

### 4.1 MCPPool

A single `MCPPool` singleton owned by the FastAPI app, started in lifespan:

```python
class MCPPool:
    _global: dict[str, MCPConnection]
    _private: dict[str, dict[str, MCPConnection]]   # organism_id → {name → conn}

    async def ensure_global(self, specs: list[MCPServerSpec]) -> None
    async def ensure_organism(self, organism_id: str, specs: list[MCPServerSpec]) -> None
    async def list_tools(self, organism_id: str) -> list[ToolDef]
    async def call(self, organism_id: str, namespaced_tool: str, args: dict,
                   *, is_dream: bool = False) -> dict
    async def shutdown(self) -> None
```

Connections are **lazy** (opened on first `list_tools` or `call`), **long-lived** (stay open across perceives), and **per-organism isolated** (organism A's private servers can't be seen by organism B).

Auto-reconnect with exponential backoff (1s, 2s, 4s, capped at 30s) if a server crashes. After 5 consecutive failures, the server is marked unhealthy in `lifecycle.status()` and skipped from tool catalogs until the operator restarts it.

### 4.2 Server discovery

Operator-curated `organisms/_mcp_global.json`:

```json
{
  "servers": [
    {"name": "filesystem", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/genesis_fs"]},
    {"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]}
  ]
}
```

Per-organism servers live in `Organism.mcp_servers` (same `MCPServerSpec` shape). New endpoints to manage them at runtime:

- `POST   /api/genesis/organisms/{id}/mcp/attach`  body = `MCPServerSpec`
- `DELETE /api/genesis/organisms/{id}/mcp/{name}`
- `GET    /api/genesis/mcp/global` — list global servers + health
- `POST   /api/genesis/mcp/global/reload` — re-read `_mcp_global.json`

### 4.3 Tool catalog → LLM

In stage `[2] load_capabilities`, we call `tools/list` on every relevant server (global + this organism's private), cache by `(server_name, tool_name)`, and present them to the LLM under namespaced names: `mcp__filesystem__read_file`, `mcp__github__create_issue`. Built-in tools keep their existing names.

The system prompt gets one extra block:

```
AVAILABLE TOOLS:
=== Built-in ===
send_slack(channel, text), http_request(method, url, ...),
remember(key, value), declare_done(reason)
=== MCP: filesystem ===
mcp__filesystem__read_file(path), mcp__filesystem__write_file(path, content), ...
=== MCP: github ===
mcp__github__create_issue(repo, title, body), ...
```

The LLM returns `{"action": {"tool": "mcp__filesystem__read_file", "args": {...}}}`. The dispatcher in stage `[4]` checks for the `mcp__` prefix; if present, splits `mcp__<server>__<tool>` and routes to `MCPPool.call(organism_id, "mcp__filesystem__read_file", args)`.

**Naming collisions:** if a built-in tool name and an MCP tool collide, the built-in wins (warned at catalog load). Two MCP tools with the same `(server, tool)` cannot collide; two MCP tools from different servers with the same tool name are disambiguated by the `mcp__server__tool` prefix.

### 4.4 Dream-mode handling

When `is_dream=True`, MCP tool calls are intercepted in stage `[4]` exactly like existing tools — the dispatcher synthesizes a plausible result via a small LLM call rather than actually calling the server. **Dreaming organisms must NEVER touch real MCP servers** (no side effects in imagination). This invariant is double-enforced:

1. The dispatcher in stage `[4]` checks `is_dream` BEFORE calling `MCPPool.call`, and routes to the dream-result synthesizer instead.
2. As a defense-in-depth backstop, `MCPPool.call(..., is_dream=True)` raises a `RuntimeError` immediately if it is ever reached.

### 4.5 Failure modes

| Failure | Behavior |
|---|---|
| Server fails to start | Logged. Organism continues without that server's tools. Marked unhealthy in `lifecycle.status()`. |
| Tool call timeout (default 30s) | Returns `{"ok": false, "error": "timeout"}`. Organism perceives the failure and can learn. |
| Server crashes mid-life | Reconnect attempted on next call. In-flight call returns error. |
| Schema mismatch on `tools/list` | Offending tool skipped, rest of catalog still works. Logged. |
| Rogue tool returns invalid JSON | Wrapped as `{"ok": false, "error": "invalid_response", "raw": "..."}`. |

### 4.6 Library choice

Use the official `mcp` Python package (`pip install mcp`). It ships an async stdio client. If it proves too heavy or buggy in practice, fall back to a ~100 LOC custom JSON-RPC stdio client. The `MCPPool` interface is library-agnostic so swapping is a one-file change.

---

## 5. Skills as Inheritable DNA

### 5.1 Inheritance at seed time

`POST /api/genesis/seed` accepts new optional fields:

```json
{
  "goal": "...",
  "inherit_from": ["sk_a1b2", "sk_c3d4"],         // explicit skill IDs
  "inherit_from_organisms": ["o_xyz"],             // OR pull from an organism's lineage
  "max_inherited_skills": 5                        // cap to prevent context bloat
}
```

`backend/genesis/skills/inherit.py` resolves these into the new organism's `inherited_skills: list[SkillRef]` and `parent_organisms: list[str]`. If both `inherit_from` and `inherit_from_organisms` are provided, take the union, then cap by `max_inherited_skills` preferring higher `fitness_at_death`.

### 5.2 Loading at perceive time

In stage `[1] gather_context`, `inherited_skills` get loaded as a context block injected before the LLM reasoning call:

```
INHERITED WISDOM (read carefully — these are skills your ancestors distilled):

=== Skill: customer_email_triage (gen 3, fitness 0.78) ===
[full markdown body]

=== Skill: vip_handling (gen 2, fitness 0.65) ===
[full markdown body]
```

**Token budget:** total Skills text capped at ~3000 tokens. If exceeded, drop lowest-fitness Skills first. The LLM is told these are **guidance, not commands** — its intent still wins if Skills conflict with the organism's `Intent`.

### 5.3 Distillation at death

`DELETE /api/genesis/organisms/{id}` triggers (BEFORE the org files are wiped):

```
backend/genesis/skills/distill.py
  ↓
1. Load all real (non-dream, non-shadow) decisions for this organism.
2. If n_real_decisions < 5 → skip distillation entirely (insufficient signal).
3. LLM call:
     system: "You are distilling a digital organism's life into a Skill that
              future organisms will inherit. Extract: what triggers matter,
              what worked, what failed, what patterns emerged."
     user: { intent, decisions[], inherited_skills_used[], fitness_score }
   → returns markdown body + structured frontmatter fields.
4. Compute generation = max(parent.generation for parent in inherited_skills) + 1
   (or 1 if no inherited skills).
5. Write organisms/_skill_pool/sk_<hash>.md (atomic via temp-file + rename).
6. Update Organism.distilled_skill_id BEFORE the organism is wiped, persist for record
   (optionally retain a tombstone organism.json under organisms/_graveyard/).
7. Emit "organism.distilled" event with new skill_id.
```

### 5.4 Pool browsing API

- `GET    /api/genesis/skills` — list all pool skills with frontmatter (no body)
- `GET    /api/genesis/skills/{skill_id}` — full markdown
- `GET    /api/genesis/skills/{skill_id}/lineage` — recursive parent tree (skills + organisms)
- `DELETE /api/genesis/skills/{skill_id}` — gardener removes a skill (rare; for cleanup)

### 5.5 Frontend additions

1. **Skill Library** panel toggled by a `📚` button in the GenesisPage header. Lists pool skills (name, generation, fitness bar, `n_decisions`, parent count). Clicking opens a modal showing the full markdown body + a mini lineage graph (parent skills + parent organisms as ReactFlow nodes). Each skill has a "🧬 Seed organism with this" button that opens the Seed modal pre-populated with that skill in the inheritance picker.
2. **Inheritance picker** in the Seed modal — multi-select skills from the pool. Templates (G1) can pre-suggest specific skill IDs.

### 5.6 Fitness placeholder

`Organism.fitness_score` exists in DNA but is computed in Phase 1 only as a simple heuristic in stage `[5] record`:

```python
fitness_score = n_successful_actions / max(n_decisions, 1)
# where success = action.result.get("ok") == True
```

This gives Phase 1 distillation something to record so Phase 3 can replace the function without changing any data shapes. The field is therefore stable for forward compatibility.

---

## 6. Polish

### 6.1 Templates (G1)

`frontend/src/components/genesis/templates.js` ships four templates:

| Template | Goal | Suggested sources | Suggested MCP |
|---|---|---|---|
| 📨 Customer Pulse | Watch emails, route urgency, draft replies. | webhook(`email_received`), interval(`health_check` 5m) | `filesystem`, `fetch` |
| 👁 Repo Sentinel | Watch GitHub events, summarize PRs, flag CVEs. | webhook(`gh_event`) | `github` |
| 📈 Market Dreamer | Poll a price feed, dream worst-case scenarios, alert on anomalies. | http_poll(`price_tick` 60s, configurable URL) | `fetch` |
| 🌱 Blank slate | Empty form, user fills everything. | — | — |

Seed modal grows a top row of template chips. Clicking one prefills name, goal, constraints, forbidden, suggested sources, and suggested MCP servers. The user can edit any field before submitting.

### 6.2 Slack noise (G2)

Root cause: `backend/main.py` lifespan starts the Slack Socket Mode bot, which throws an `aiohttp.ClientConnectorCertificateError` on this dev machine because the local Python install is missing CA certs. This produces a wall of stack trace at startup that drowns useful logs.

Fix:

1. Wrap Slack startup in a `_safe_start_slack_bot()` task that catches all exceptions and emits one warning line instead of a stack trace.
2. Add a `SLACK_DISABLED=1` env var that short-circuits Slack startup entirely. Document in `.env.example` with a note about the local cert issue.
3. Reduce Slack module log level to `WARNING` by default to avoid further noise.

### 6.3 Hero demo "Tour" (G3)

`frontend/src/components/genesis/Tour.jsx` — a small state machine triggered by a "▶ Tour" button on the GenesisPage. Six steps, ~50s total, skippable, replayable. Each step has a tooltip overlay pointing at the relevant DOM element with the narration.

| # | Duration | Narration | Action |
|---|---|---|---|
| 1 | 5s | "Meet Genesis. Watch this organism be born." | `POST /seed` with `customer_pulse` template + 2 inherited skills (creating them on-the-fly if pool empty). Highlight the nucleus. |
| 2 | 8s | "It can perceive." | `POST /perceive` with synthetic urgent email. Highlight the new node in the graph. |
| 3 | 12s | "And it dreams." | `POST /dream n=5`. Highlight ghost nodes streaming in. |
| 4 | 10s | "You can rewrite its past." | Auto-click an early decision, open inspector, fill `new_action`, submit edit. Highlight the shadow branch. |
| 5 | 6s | "Promote a counterfactual to reality." | `POST /promote`. Highlight the timeline mutation. |
| 6 | 8s | "When it dies, its mind becomes inheritable." | `DELETE` organism. Highlight the new skill in the Skill Library. Fade in: "This is digital evolution." |

For step 1, if the pool is empty, the Tour first creates two seed Skills programmatically so the inheritance path is visible.

### 6.4 Skill Library UI (G4)

Already specified in §5.5. Listed here for discoverability.

---

## 7. Build Order (Cutover Plan)

Steps 1–9 are backend-only and independently testable via curl. Steps 10–13 are pure UI.

```
1. types.py          — add MCPServerSpec, SkillRef, organism fields
2. pipeline/stages.py — extract perceive into 5 stages (refactor only, behavior identical)
3. skills/pool.py    — read/write pool files
4. skills/distill.py — LLM distillation on organism death
5. skills/inherit.py — load skills at seed/perceive
6. mcp/client.py     — MCPPool
7. mcp/catalog.py    — global ambient server config
8. api.py            — new endpoints (/skills/*, /mcp/*, seed extensions)
9. lifecycle.py      — call distill.py before organism teardown
10. frontend hook    — useGenesis: + skills, + mcpServers, + inherit
11. SkillLibrary.jsx — pool browser UI
12. Templates + Tour — polish
13. Slack noise + .env.example
```

Step 2 (pipeline refactor) is the riskiest single step. It must be done as a pure refactor: `runtime.perceive()`'s public signature does not change, and existing tests/smoke flows must pass identically before any new feature work proceeds.

---

## 8. Test Surface

Three smoke tests minimum (`backend/tests/genesis/`):

1. **`test_skill_lifecycle.py`** — seed organism → 5 perceives → kill → assert skill file exists in `_skill_pool/` with correct frontmatter (right `parent_organisms`, `n_decisions_distilled=5`, `generation=1`).
2. **`test_skill_inheritance.py`** — manually plant skill A in the pool → seed organism inheriting A → perceive → assert A's body text appears verbatim in the LLM prompt sent during reasoning. Use a recorded LLM client to inspect the prompt.
3. **`test_mcp_dispatch.py`** — start a mock MCP stdio server with one tool (`echo`) → seed organism with it as private MCP → mock LLM to return `{"action": {"tool": "mcp__mock__echo", "args": {"x": 1}}}` → assert `MCPPool` routed to the mock server and the result was recorded in the Decision.

Beyond the smoke tests, the existing Genesis end-to-end test (`/tmp/genesis_ws_test_server.py` flow) must still pass after the pipeline refactor in step 2.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| MCP servers slow down perception (subprocess spawn + tool list per perceive) | Lazy connect + persistent connections; tool catalog cached for the connection's lifetime; `tools/list` only re-queried on reconnect. |
| Inherited Skills bloat the prompt and slow reasoning | Hard 3000-token budget on Skills block; lowest-fitness Skills evicted first. |
| Distillation produces bad Skills that poison future organisms | Pool browser UI lets the operator delete bad Skills; fitness scoring (Phase 3) will drown them out at scale. |
| `mcp` Python package immature/unstable | Library swap is a one-file change behind `MCPPool`. Fallback to custom 100-LOC JSON-RPC client documented. |
| Pipeline refactor breaks existing causality.edit_and_replay flow | Pipeline refactor is a single PR with the existing smoke test as a hard gate. |
| Skill files written to disk during a crash mid-distillation leave half-files | Distillation writes to a temp file and atomically renames into `_skill_pool/`. |

---

## 10. Open Questions for Implementation

These are intentionally left for the implementation plan (writing-plans) to resolve:

1. Exact LLM prompt template for `distill.py` — needs iteration with real organism data.
2. Whether to run distillation synchronously (block the DELETE response) or async (return 202 and emit event later). Recommend sync for predictable demo behavior; revisit if it gets slow.
3. UI affordance for the inheritance picker in the Seed modal: searchable list vs. cards vs. lineage graph picker.
4. Whether pool Skills should be auto-garbage-collected at some threshold (e.g., > 1000 unused skills) — defer to a Phase 3 concern (fitness will naturally weed them).
