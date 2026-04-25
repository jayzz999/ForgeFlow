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

    # Truncate decision payloads to fit in small LLM context windows
    compact_decisions = []
    for d in decisions[-8:]:  # last 8 decisions max
        result_ok = d.result.get("ok") if isinstance(d.result, dict) else None
        compact_decisions.append({
            "action": d.action.get("name", "?"),
            "args_summary": str(d.action.get("args", {}))[:100],
            "reasoning": d.reasoning[:200],
            "result_ok": result_ok,
        })

    user_payload = {
        "intent": org.intent.goal[:300],
        "constraints": org.intent.constraints[:3],
        "forbidden": org.intent.forbidden[:3],
        "fitness_score": org.fitness_score,
        "decision_count": len(decisions),
        "decisions": compact_decisions,
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
        logger.warning(f"[distill] {organism_id} LLM response unparseable, using heuristic fallback")
        # Heuristic fallback — build a basic Skill from raw decision data
        actions_used = list({d.action.get("name", "?") for d in decisions})
        triggers_seen = list({d.trigger.get("type", "?") for d in decisions})
        ok_count = sum(1 for d in decisions if isinstance(d.result, dict) and d.result.get("ok"))
        fail_count = len(decisions) - ok_count
        parsed = {
            "name": f"organism_{organism_id[:8]}_skill",
            "description": f"Distilled from {len(decisions)} decisions (goal: {org.intent.goal[:60]}...)",
            "trigger_patterns": triggers_seen,
            "forbidden_patterns": list(org.intent.forbidden[:3]),
            "body": (
                f"# What this knows\n"
                f"- Intent: {org.intent.goal[:200]}\n"
                f"- Tools used: {', '.join(actions_used)}\n\n"
                f"# What worked\n"
                f"- {ok_count}/{len(decisions)} decisions succeeded\n"
                f"- Actions that worked: {', '.join(a for a in actions_used if a != 'noop')}\n\n"
                f"# What failed\n"
                f"- {fail_count}/{len(decisions)} decisions failed\n"
                f"- Constraints: {', '.join(org.intent.constraints[:3])}\n\n"
                f"# Patterns observed\n"
                f"- Trigger types: {', '.join(triggers_seen)}\n"
                f"- Learned patterns: {', '.join(org.learned_patterns[:5]) if org.learned_patterns else 'none'}\n"
            ),
        }

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

    # Phase 4: Embodiment — compile the skill into an executable MCP server
    try:
        from . import compiler
        compiled_path = await compiler.compile_skill(skill, decisions)
        if compiled_path:
            logger.info(f"[distill] Phase 4: Compiled {skill.skill_id} → {compiled_path}")
        else:
            logger.warning(f"[distill] Phase 4: Compilation failed for {skill.skill_id} (non-fatal)")
    except Exception as e:
        logger.warning(f"[distill] Phase 4: Compilation error for {skill.skill_id}: {e} (non-fatal)")

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
