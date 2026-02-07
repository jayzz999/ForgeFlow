"""Workflow Store — Persists generated workflows to disk and SQLite.

This makes ForgeFlow REAL:
- Workflows saved as proper project folders on disk
- Metadata tracked in SQLite for history/status
- Each workflow gets: workflow.py, requirements.txt, .env.example, run.sh
"""

import json
import os
import re
import sqlite3
import stat
from datetime import datetime
from pathlib import Path

from backend.shared.config import settings

# ── Paths ─────────────────────────────────────────────────────

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workflows")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "forgeflow.db")


def _ensure_dirs():
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            user_request TEXT,
            status TEXT DEFAULT 'deployed',
            code_path TEXT,
            dag_json TEXT,
            debug_attempts INTEGER DEFAULT 0,
            services TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


# ── Extract Dependencies ──────────────────────────────────────

def _extract_requirements(code: str) -> str:
    """Parse import statements to generate requirements.txt."""
    stdlib = {
        "asyncio", "os", "sys", "json", "re", "time", "datetime",
        "collections", "functools", "itertools", "pathlib", "logging",
        "typing", "uuid", "hashlib", "base64", "urllib", "tempfile",
        "math", "random", "string", "io", "struct", "csv", "enum",
    }
    pip_map = {
        "httpx": "httpx>=0.26.0",
        "websockets": "websockets>=12.0",
        "requests": "requests>=2.31.0",
        "aiohttp": "aiohttp>=3.9.0",
        "slack_sdk": "slack-sdk>=3.27.0",
        "google": "google-api-python-client>=2.0.0",
    }

    imports = set()
    for line in code.split("\n"):
        line = line.strip()
        if line.startswith("import "):
            mod = line.split()[1].split(".")[0]
            imports.add(mod)
        elif line.startswith("from "):
            mod = line.split()[1].split(".")[0]
            imports.add(mod)

    deps = []
    for mod in sorted(imports):
        if mod in stdlib or mod.startswith("_"):
            continue
        if mod in pip_map:
            deps.append(pip_map[mod])
        elif mod not in stdlib:
            deps.append(mod)

    return "\n".join(deps) + "\n" if deps else "# No external dependencies\n"


def _extract_env_vars(code: str) -> str:
    """Extract os.getenv() calls to generate .env.example."""
    pattern = r'os\.getenv\(["\'](\w+)["\']'
    vars_found = re.findall(pattern, code)
    if not vars_found:
        return "# No environment variables needed\n"

    lines = ["# ForgeFlow Workflow Environment Variables", "# Copy this to .env and fill in your values", ""]
    for var in sorted(set(vars_found)):
        lines.append(f"{var}=your_{var.lower()}_here")
    return "\n".join(lines) + "\n"


# ── Save Workflow ─────────────────────────────────────────────

def save_workflow(
    workflow_id: str,
    name: str,
    description: str,
    user_request: str,
    code: str,
    dag: dict,
    debug_attempts: int = 0,
    services: list[str] | None = None,
    extra_files: dict[str, str] | None = None,
) -> dict:
    """Save a workflow as a project folder + DB record. Returns metadata."""
    _ensure_dirs()

    # Create project folder
    project_dir = os.path.join(WORKFLOWS_DIR, workflow_id)
    os.makedirs(project_dir, exist_ok=True)

    # 1. Write workflow.py
    workflow_file = os.path.join(project_dir, "workflow.py")
    with open(workflow_file, "w") as f:
        f.write(code)

    # 2. Write requirements.txt
    req_file = os.path.join(project_dir, "requirements.txt")
    with open(req_file, "w") as f:
        f.write(_extract_requirements(code))

    # 3. Write .env.example
    env_file = os.path.join(project_dir, ".env.example")
    with open(env_file, "w") as f:
        f.write(_extract_env_vars(code))

    # 4. Write run.sh
    run_file = os.path.join(project_dir, "run.sh")
    with open(run_file, "w") as f:
        f.write(f"""#!/bin/bash
# ForgeFlow Workflow Runner — {name}
# Generated: {datetime.utcnow().isoformat()}Z
# Workflow ID: {workflow_id}

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Install dependencies
pip install -r requirements.txt -q

# Run workflow
python workflow.py
""")
    os.chmod(run_file, os.stat(run_file).st_mode | stat.S_IEXEC)

    # 5. Write README.md for the workflow
    readme_file = os.path.join(project_dir, "README.md")
    services_list = services or []
    with open(readme_file, "w") as f:
        f.write(f"""# {name}

> {description}

**Generated by ForgeFlow** | ID: `{workflow_id}` | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

## Services Used
{chr(10).join(f'- {s}' for s in services_list) if services_list else '- None detected'}

## Quick Start

```bash
# Option 1: Run locally
make run

# Option 2: Docker
make docker-compose

# Option 3: Kubernetes
make k8s-deploy
```

## All Deployment Options

| Platform | Command | Requirements |
|----------|---------|--------------|
| Local | `make run` or `bash run.sh` | Python 3.11+, pip |
| Docker | `make docker` | Docker |
| Docker Compose | `make docker-compose` | Docker Compose |
| Kubernetes | `make k8s-deploy` | kubectl, cluster |

## Files
- `workflow.py` — Main workflow code
- `requirements.txt` — Python dependencies
- `.env.example` — Environment variable template
- `run.sh` — One-command runner
- `Dockerfile` — Container deployment
- `docker-compose.yml` — Docker orchestration
- `k8s-deployment.yaml` — Kubernetes manifest
- `Makefile` — Multi-platform deployment targets

{"## Self-Debug History" + chr(10) + f"This workflow required {debug_attempts} fix(es) before passing." if debug_attempts > 0 else ""}
""")

    # 6. Write DAG as JSON for reference
    dag_file = os.path.join(project_dir, "dag.json")
    with open(dag_file, "w") as f:
        json.dump(dag, f, indent=2, default=str)

    # 7. Write Dockerfile for containerized deployment
    dockerfile = os.path.join(project_dir, "Dockerfile")
    with open(dockerfile, "w") as f:
        f.write(f"""# ForgeFlow Workflow Container — {name}
# Generated: {datetime.utcnow().isoformat()}Z
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy workflow files
COPY . .

# Run the workflow
CMD ["python", "workflow.py"]
""")

    # 8. Write docker-compose.yml for easy orchestration
    compose_file = os.path.join(project_dir, "docker-compose.yml")
    env_vars_yaml = ""
    env_vars_list = re.findall(r'os\.getenv\(["\'](\w+)["\']', code)
    for var in sorted(set(env_vars_list)):
        env_vars_yaml += f"      - {var}=${{{var}}}\n"

    with open(compose_file, "w") as f:
        f.write(f"""# ForgeFlow Workflow — {name}
# Run: docker-compose up
version: "3.8"

services:
  workflow:
    build: .
    container_name: forgeflow-{workflow_id}
    env_file:
      - .env
{('    environment:' + chr(10) + env_vars_yaml) if env_vars_yaml else ''}    restart: "no"
""")

    # 9. Write Kubernetes deployment manifest
    k8s_file = os.path.join(project_dir, "k8s-deployment.yaml")
    k8s_env_block = ""
    for var in sorted(set(env_vars_list)):
        k8s_env_block += f"""        - name: {var}
          valueFrom:
            secretKeyRef:
              name: forgeflow-{workflow_id}-secrets
              key: {var.lower()}
"""

    k8s_default_env = f'        - name: WORKFLOW_ID\n          value: "{workflow_id}"\n'
    k8s_secret_lines = [f'  {v.lower()}: "your_{v.lower()}_here"' for v in sorted(set(env_vars_list))]
    k8s_secret_data = "\n".join(k8s_secret_lines) if k8s_secret_lines else '  placeholder: "none"'

    with open(k8s_file, "w") as f:
        f.write(f"""# ForgeFlow Workflow — {name}
# Deploy: kubectl apply -f k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: forgeflow-{workflow_id}
  labels:
    app: forgeflow
    workflow: "{workflow_id}"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: forgeflow-{workflow_id}
  template:
    metadata:
      labels:
        app: forgeflow-{workflow_id}
    spec:
      containers:
      - name: workflow
        image: forgeflow-{workflow_id}:latest
        imagePullPolicy: IfNotPresent
        env:
{k8s_env_block if k8s_env_block else k8s_default_env}        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
      restartPolicy: Always
---
apiVersion: v1
kind: Secret
metadata:
  name: forgeflow-{workflow_id}-secrets
type: Opaque
stringData:
{k8s_secret_data}
""")

    # 10. Write Makefile for easy multi-platform deployment
    makefile = os.path.join(project_dir, "Makefile")
    with open(makefile, "w") as f:
        f.write(f"""# ForgeFlow Workflow — {name}
# Multi-platform deployment targets

.PHONY: run docker docker-build k8s-deploy k8s-delete test clean

# Local execution
run:
\tcp .env.example .env 2>/dev/null || true
\tpip install -r requirements.txt -q
\tpython workflow.py

# Docker deployment
docker-build:
\tdocker build -t forgeflow-{workflow_id} .

docker: docker-build
\tdocker run --env-file .env forgeflow-{workflow_id}

docker-compose:
\tcp .env.example .env 2>/dev/null || true
\tdocker-compose up --build

# Kubernetes deployment
k8s-deploy: docker-build
\tkubectl apply -f k8s-deployment.yaml

k8s-delete:
\tkubectl delete -f k8s-deployment.yaml

k8s-logs:
\tkubectl logs -l app=forgeflow-{workflow_id} -f

# Testing
test:
\tpython -m pytest test_workflow.py -v 2>/dev/null || python -c "exec(open('workflow.py').read())"

# Cleanup
clean:
\tdocker-compose down 2>/dev/null || true
\tdocker rmi forgeflow-{workflow_id} 2>/dev/null || true
""")

    # 6b. Write extra files from multi-file generation
    extra_file_names = []
    if extra_files:
        for rel_path, content in extra_files.items():
            normalized = os.path.normpath(rel_path)
            if normalized.startswith("..") or os.path.isabs(normalized):
                continue  # Skip unsafe paths
            full_path = os.path.join(project_dir, normalized)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)
            extra_file_names.append(normalized)

    # 7. Save to SQLite
    db = _get_db()
    db.execute("""
        INSERT OR REPLACE INTO workflows
        (id, name, description, user_request, status, code_path, dag_json, debug_attempts, services, updated_at)
        VALUES (?, ?, ?, ?, 'deployed', ?, ?, ?, ?, datetime('now'))
    """, (
        workflow_id, name, description, user_request,
        project_dir, json.dumps(dag, default=str),
        debug_attempts, ",".join(services_list),
    ))
    db.commit()
    db.close()

    all_files = ["workflow.py", "requirements.txt", ".env.example", "run.sh", "Dockerfile", "docker-compose.yml", "k8s-deployment.yaml", "Makefile", "README.md", "dag.json"] + extra_file_names

    return {
        "workflow_id": workflow_id,
        "project_dir": project_dir,
        "files": all_files,
        "status": "deployed",
    }


# ── Query Workflows ──────────────────────────────────────────

def list_workflows(limit: int = 20) -> list[dict]:
    """List all saved workflows."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, name, description, status, services, debug_attempts, created_at FROM workflows ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_workflow(workflow_id: str) -> dict | None:
    """Get a single workflow by ID."""
    db = _get_db()
    row = db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    db.close()
    if not row:
        return None
    result = dict(row)
    # Load code from disk
    code_path = result.get("code_path", "")
    if code_path and os.path.exists(os.path.join(code_path, "workflow.py")):
        with open(os.path.join(code_path, "workflow.py")) as f:
            result["code"] = f.read()
    return result


def get_workflow_project_path(workflow_id: str) -> str | None:
    """Get the project folder path for a workflow."""
    path = os.path.join(WORKFLOWS_DIR, workflow_id)
    return path if os.path.exists(path) else None
