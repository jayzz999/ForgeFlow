#!/usr/bin/env python3
"""Smoke-check a ForgeFlow production/staging runtime."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


BASE_URL = os.getenv("FORGEFLOW_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def get_json(path: str) -> dict:
    with urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    checks = [
        ("/api/health", lambda payload: payload.get("status") == "ok"),
        ("/api/status", lambda payload: payload.get("status") == "ok"),
        ("/api/product/overview", lambda payload: "metrics" in payload),
        ("/api/production/readiness", lambda payload: "checks" in payload and "blockers" in payload),
    ]
    failures = []
    for path, validator in checks:
        try:
            payload = get_json(path)
            ok = validator(payload)
            print(f"{'PASS' if ok else 'FAIL'} {path}")
            if path == "/api/production/readiness":
                print(f"  score={payload.get('score')} ready={payload.get('ready')} production={payload.get('production_mode')}")
                for item in payload.get("blockers", []) + payload.get("warnings", []):
                    print(f"  - {item.get('status')} {item.get('id')}: {item.get('detail')}")
            if not ok:
                failures.append(path)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"FAIL {path}: {exc}")
            failures.append(path)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
