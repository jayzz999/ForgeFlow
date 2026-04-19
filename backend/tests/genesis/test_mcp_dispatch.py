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
