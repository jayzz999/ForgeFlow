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
