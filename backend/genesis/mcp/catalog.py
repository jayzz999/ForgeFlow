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
