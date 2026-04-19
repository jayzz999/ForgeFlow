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
