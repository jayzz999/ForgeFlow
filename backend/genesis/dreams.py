"""Imagination engine — speculative dreaming during organism idle time.

The organism doesn't wait for reality. During idle cycles, it asks itself:
"What kinds of perceptions might I face soon?" — generates plausible
hypothetical events using its intent + recent reality as context, then runs
the runtime against each one in DREAM mode (no real side effects).

Outcomes are stored as Decisions with is_dream=True. The live runtime can
later cite these dreams when a real perception matches a dreamt one ("I have
already imagined this; here is what I would do").

This is mental simulation as first-class infrastructure. No production
workflow tool does this.
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, Optional

from backend.shared.gemini_client import generate_text

from . import runtime, store
from .types import Organism, OrganismState

logger = logging.getLogger("genesis.dreams")


DREAM_GENERATOR_SYSTEM = """You imagine plausible-but-not-yet-occurred
perception events for a living digital organism. Your job is to generate
diverse, useful hypothetical triggers it might face soon, so it can mentally
rehearse before reality demands a response.

Return STRICT JSON: a list of perception objects. Each perception is a dict
with at least a 'type' field and any other fields realistic for that event.

Make the set DIVERSE: include common cases, edge cases, adversarial cases,
and time-of-day variations. Avoid duplicates. Avoid trivia.
"""


async def imagine(
    organism_id: str,
    *,
    n: Optional[int] = None,
    event_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
) -> list[dict]:
    """Run one dreaming cycle. Returns the list of dream perceptions tried."""
    org = store.load_organism(organism_id)
    if not org:
        raise ValueError(f"organism {organism_id} not found")

    n = n or org.dream_budget_per_cycle
    org.state = OrganismState.DREAMING
    store.save_organism(org)

    if event_callback:
        await event_callback("organism.dreaming_start", {"organism_id": organism_id, "budget": n})

    perceptions = await _generate_hypothetical_perceptions(org, n=n)
    logger.info(f"[Dreams] org {organism_id} imagining {len(perceptions)} scenarios")

    for i, p in enumerate(perceptions):
        try:
            await runtime.perceive(
                organism_id=organism_id,
                perception=p,
                is_dream=True,
                event_callback=event_callback,
            )
            if event_callback:
                await event_callback("organism.dreamt", {
                    "organism_id": organism_id, "i": i + 1, "of": len(perceptions),
                    "perception": p,
                })
        except Exception as e:
            logger.warning(f"[Dreams] scenario {i} failed: {e}")

    org.state = OrganismState.PERCEIVING
    store.save_organism(org)

    if event_callback:
        await event_callback("organism.dreaming_end",
                             {"organism_id": organism_id, "imagined": len(perceptions)})

    return perceptions


async def _generate_hypothetical_perceptions(org: Organism, *, n: int) -> list[dict]:
    """Ask the LLM to invent N plausible perception events the organism might face."""
    real_history = [
        {"trigger": d.trigger, "action": d.action}
        for d in store.all_decisions(org.id, include_dreams=False)[-5:]
    ]
    prompt = json.dumps({
        "intent": org.intent.goal,
        "constraints": org.intent.constraints,
        "recent_real_perceptions": real_history,
        "instructions": (
            f"Generate exactly {n} diverse hypothetical perception events this "
            f"organism might face in the near future. Return JSON list."
        ),
    }, indent=2, default=str)

    raw = await generate_text(
        prompt=prompt,
        system=DREAM_GENERATOR_SYSTEM,
        temperature=0.9,  # high — we want diversity
        max_tokens=1500,
    )
    return _extract_json_list(raw)


def _extract_json_list(text: str) -> list[dict]:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return [d for d in v if isinstance(d, dict)]
    except Exception:
        pass
    # Last-ditch: scan for [ ... ]
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1:
        try:
            data = json.loads(s[i : j + 1])
            return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
    return []
