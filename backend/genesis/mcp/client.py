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

    async def list_tools(self, organism_id: str) -> list[dict]:
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
