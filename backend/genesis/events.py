"""Event bridge — Genesis events → external listeners (e.g. WebSocket broadcaster).

Genesis modules emit events via `emit(event_type, payload)`. The web layer
registers a listener with `subscribe(callback)`. This decouples runtime/dreams
from FastAPI.

All Genesis events have shape:
    {
        "type": "organism.<verb>",   # see EVENT_TYPES below
        "organism_id": "o_...",
        "ts": "2026-...",
        ... event-specific fields ...
    }
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable

logger = logging.getLogger("genesis.events")

# Event vocabulary — keep tight and meaningful.
EVENT_TYPES = {
    "organism.seeded",          # new organism crystallized
    "organism.perceiving",       # received an event, about to reason
    "organism.reasoning",        # LLM produced reasoning + intended action
    "organism.acted",            # action executed (with result)
    "organism.dreaming_start",   # imagination cycle starting
    "organism.dreamt",           # one dream perception completed
    "organism.dreaming_end",     # imagination cycle complete
    "organism.edited",           # past decision was retroactively edited
    "organism.branch_created",   # counterfactual branch built
    "organism.branch_promoted",  # branch became canonical reality
    "organism.died",             # organism removed
}


_subscribers: list[Callable[[dict], Awaitable[None]]] = []


def subscribe(callback: Callable[[dict], Awaitable[None]]) -> None:
    """Register an async listener. The web layer calls this once at startup."""
    _subscribers.append(callback)


def unsubscribe(callback: Callable[[dict], Awaitable[None]]) -> None:
    if callback in _subscribers:
        _subscribers.remove(callback)


async def emit(event_type: str, payload: dict | None = None) -> None:
    """Fire an event to all subscribers. Never raises — listener errors are
    caught and logged so they cannot kill the runtime mid-reasoning."""
    if event_type not in EVENT_TYPES:
        logger.warning(f"unknown event type: {event_type}")
    event = {"type": event_type, "ts": datetime.utcnow().isoformat()}
    if payload:
        event.update(payload)
    for cb in list(_subscribers):
        try:
            await cb(event)
        except Exception as e:
            logger.error(f"subscriber {cb} raised on {event_type}: {e}")


def make_callback() -> Callable[[str, dict], Awaitable[None]]:
    """Return an event_callback compatible with runtime/dreams signatures.

    Runtime expects callback(event_type: str, data: dict). We translate that
    into emit() calls so all events flow through the same bus.
    """
    async def cb(event_type: str, data: dict) -> None:
        await emit(event_type, data)
    return cb
