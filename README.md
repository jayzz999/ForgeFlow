# ForgeFlow

ForgeFlow turns plain-English business requests into grounded automation workflows and runnable software artifacts. It can collect requirements conversationally, discover APIs, import OpenAPI/MCP capabilities, validate credentials, preview risky actions, run durable jobs, generate app-builder artifacts, and prepare deployment targets.

## What It Does

Most automation tools expect users to know APIs, auth, schemas, and workflow internals. ForgeFlow tries to bridge that translation layer:

| Layer | Component | What It Does |
|-------|-----------|-------------|
| 1 | Conversation Engine | Extracts requirements from natural language and asks targeted clarification questions |
| 2 | API + Tool Discovery | Searches built-in connectors, imported OpenAPI specs, MCP manifests, and public API directories |
| 3 | Canonical Spec Compiler | Converts prompts into typed workflow specs with steps, connector contracts, tests, approvals, and deployment targets |
| 4 | Credential Center | Stores encrypted credentials, starts OAuth flows, rotates secrets, probes connectors, and reports missing credentials per workflow |
| 5 | Runtime Planner | Produces safe live-execution plans with required fields, credentials, approval state, request previews, and compensation hints |
| 6 | Durable Runtime | Queues webhook/scheduled/manual jobs, retries failures, dead-letters exhausted jobs, records run logs, and recovers stale running items |
| 7 | Code Generator + Sandbox | Generates Python workflow packages, reviews them, tests them, executes them in Docker when available, and self-debug patches failures |
| 8 | App Builder | Routes software prompts, such as games or web apps, into runnable HTML/CSS/JS artifacts with QA checks and package downloads |
| 9 | Deployment Planner | Prepares Docker, GitHub Actions, Render, Vercel, and webhook-runtime deployment dispatches with readiness checks |

## Architecture

```
User Request
    |
    v
Conversation Engine
    |
    v
API / OpenAPI / MCP Discovery
    |
    v
Canonical Automation Spec
    |
    v
Credential + Approval Preflight
    |
    v
Dry Run / Execution Plan
    |
    v
Queue Worker / Webhook / Schedule
    |
    v
Live Connector Runtime OR Codegen Sandbox <--> Self-Debug Loop
    |
    v
Deployment Dispatch / App Package
```

## Product Modes

ForgeFlow has three main workspaces:

- **Automation Builder**: prompt to generated Python workflow project.
- **Runtime**: prompt to canonical automation spec, dry-run ledger, credential checks, live execution planning, approvals, exports, and repair.
- **App Builder**: prompt to runnable app/game/site artifact with live preview, QA checks, and zip download.

Demo replay still exists for walkthroughs, but production mode blocks demo endpoints unless explicitly enabled.

## Real Integrations

ForgeFlow supports both built-in connectors and dynamically imported tools.

| Service | Auth Method | Capabilities |
|---------|-------------|--------------|
| Slack | Bot Token / OAuth | Post messages, create channels, read-only auth probe |
| Gmail | OAuth / token | Send email, create drafts, read-only profile probe |
| Google Sheets | OAuth / token | Append rows, read ranges |
| Google Calendar | OAuth / token | Create events |
| Stripe | API Key | Retrieve payments, create refunds with approval |
| Zendesk | API Token | Create tickets |
| HubSpot | Bearer Token | Create contacts, update deals |
| Okta | API Token | Create users, assign groups |
| Salesforce, Jira, Notion, Airtable, Teams | Provider tokens | Typed request generation and live-readiness planning |
| HTTP/Webhooks | URL/API token | Generic validated HTTP requests |
| OpenAPI Imports | Spec-defined auth | Operations become capabilities automatically |
| MCP Manifests | Tool-defined auth | Tools become JSON-RPC execution capabilities |

Live execution is approval-first. If credentials, required fields, or approvals are missing, ForgeFlow blocks the run and explains the next action instead of pretending the workflow deployed.

## Runtime APIs

Useful backend endpoints:

```bash
GET  /api/production/readiness
POST /api/openapi/ingest
POST /api/openapi/import-url
POST /api/mcp/discover
POST /api/specs/compile
GET  /api/specs/{spec_id}/credentials
POST /api/runtime/specs/{spec_id}/execution-plan
POST /api/runtime/specs/{spec_id}/dry-run
POST /api/runtime/specs/{spec_id}/execute-live
POST /api/queue
POST /api/queue/{queue_id}/process
POST /api/queue/process-due
POST /api/queue/recover-stale
POST /api/runtime/runs/{run_id}/repair/retest
```

## Quick Start

```bash
git clone https://github.com/jayzz999/ForgeFlow.git
cd ForgeFlow

pip install -r backend/requirements.txt
cp .env.example .env

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Docker Compose

```bash
docker-compose up --build
```

The frontend runs on `http://localhost:3000` and the backend on `http://localhost:8000`.

## Production Mode

ForgeFlow now has an explicit production readiness boundary:

```bash
FORGEFLOW_ENV=production
curl http://127.0.0.1:8000/api/production/readiness
```

In production mode, cached demo endpoints are blocked unless `FORGEFLOW_ENABLE_DEMO_ENDPOINTS=1`, live execution still requires approval, and readiness reports missing vault keys, weak admin tokens, connector credentials, queue workers, MCP runtime ingestion, and deployment targets. See `docs/PRODUCTION.md` and `.env.production.example`.

Production rehearsal:

```bash
cp .env.production.example .env.production
docker compose -f docker-compose.prod.yml --env-file .env.production up --build
python scripts/production_smoke.py
```

## Reliability And Safety

- CI runs backend tests and the frontend production build on every push and pull request.
- A mocked end-to-end smoke test verifies the pipeline can produce and save a workflow without paid LLM calls.
- Generated workflow runs are protected by `FORGEFLOW_ADMIN_TOKEN`.
- Workflow execution uses a temporary run directory and only receives allowlisted service environment variables.
- Live connector execution requires explicit approval and safe request planning.
- Queue workers support retries, backoff, dead letters, scheduled triggers, webhook triggers, and stale job recovery.
- Connector errors are classified into credential, approval, missing-field, provider, endpoint, timeout, and repair/retest actions.
- Deployment packages include an `artifacts/` folder with structured requirements, DAG, security, test, execution, and debug data.
- Old workflow packages can be deleted individually or pruned through the admin API.

## Tech Stack

| Component | Technology |
|-----------|------------|
| AI Pipeline | LangGraph |
| LLM | Groq by default, Gemini optional |
| Embeddings | Local ChromaDB default by default, Gemini optional |
| Vector Store | ChromaDB |
| Backend | FastAPI + WebSocket |
| Frontend | React + Vite + React Flow + Tailwind CSS |
| Sandbox | Docker primary, AST validation fallback |
| Slack Bot | Slack Bolt Socket Mode |
| Runtime DB | SQLite by default; mount or replace for production |

## Project Structure

```
backend/
  main.py                # FastAPI app, REST API, WebSocket API
  graph.py               # LangGraph workflow generation pipeline
  conversation/          # Requirement extraction and clarification
  discovery/             # API specs, vector store, API selection
  planner/               # DAG building and data mapping
  codegen/               # LLM code generation, tests, security review
  execution/             # Docker sandbox, AST fallback, self-debugger
  deployment/            # Workflow persistence and downloadable packages
  feedback/              # Feedback and pattern learning
  integrations/          # Slack, Gmail, Sheets, HTTP clients
  modifier/              # Natural-language workflow modification
  slack/                 # Slack bot and event notifications
  shared/                # Config, models, security helpers
  tests/                 # Backend tests

frontend/
  src/
    App.jsx
    hooks/
      useWebSocket.js
      useForgeFlow.js
    components/
      ChatPanel.jsx
      WorkflowCanvas.jsx
      CodePanel.jsx
      StatusBar.jsx
      ApiDiscoveryBadge.jsx
      DebugOverlay.jsx

workflows/               # Generated workflow projects
app_builds/              # Generated app-builder artifacts
docs/PRODUCTION.md       # Production readiness/deployment notes
docker-compose.prod.yml  # Production rehearsal compose file
```

## Environment Variables

```env
LLM_PROVIDER=groq
LLM_FALLBACK_PROVIDER=gemini
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_FAST_MODEL=llama-3.1-8b-instant
GROQ_MAX_RETRIES=2
GROQ_RETRY_BASE_SECONDS=1

# Optional Gemini fallback
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

EMBEDDING_PROVIDER=local

SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_NOTIFICATION_CHANNEL=#forgeflow-alerts
SLACK_DISABLED=0

GMAIL_ADDRESS=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password

GOOGLE_API_KEY=your-api-key
GOOGLE_SHEET_ID=your-spreadsheet-id

CHROMA_PERSIST_DIR=./chroma_db
SANDBOX_TIMEOUT=60
FORGEFLOW_ADMIN_TOKEN=change-me
FORGEFLOW_ALLOW_UNAUTH_DANGEROUS=0
FORGEFLOW_ENV=development
FORGEFLOW_ENABLE_DEMO_ENDPOINTS=1
FORGEFLOW_VAULT_KEY=
FORGEFLOW_QUEUE_WORKER=0
FORGEFLOW_RUNTIME_BASE_URL=
FORGEFLOW_MCP_RUNTIME_ENABLED=0
```

`FORGEFLOW_ADMIN_TOKEN` is required for endpoints that execute generated workflow code unless `FORGEFLOW_ALLOW_UNAUTH_DANGEROUS=1` is explicitly set for local demos.

Check runtime configuration without exposing secrets:

```bash
curl http://localhost:8000/api/status
```

The status response reports the active LLM provider, selected models, embedding provider, configured service flags, and required environment variable names only.

## License

MIT
