# ForgeFlow

ForgeFlow turns plain-English workflow descriptions into deployed Python automation projects. It discovers APIs, builds an execution DAG, generates code, tests it, self-debug patches failures, and saves a runnable deployment package.

## What It Does

Most automation tools connect pre-built blocks. ForgeFlow generates the workflow project itself:

| Layer | Component | What It Does |
|-------|-----------|-------------|
| 1 | Conversation Engine | Extracts requirements from natural language and asks targeted clarification questions |
| 2 | Semantic API Discovery | Finds matching APIs from indexed service specs using ChromaDB vector search |
| 3 | DAG Planner | Builds dependency-aware workflow steps and data mappings |
| 4 | Code Generator | Uses Gemini tool calling to research APIs and write executable Python |
| 5 | Security Review | Scans generated code for unsafe patterns |
| 6 | Test Generator | Creates pytest coverage for the generated workflow |
| 7 | Sandbox Execution | Runs code in Docker when available, with AST validation as fallback |
| 8 | Self-Debugger | Diagnoses failures, patches code, and retries |
| 9 | Deployment | Saves a complete runnable project with Docker, Compose, Makefile, README, and env template |

## Architecture

```
User Request
    |
    v
Conversation Engine
    |
    v
API Discovery
    |
    v
DAG Planner
    |
    v
Code Generator
    |
    v
Security Review
    |
    v
Test Generator
    |
    v
Sandbox Execute <--> Self-Debug Loop
    |
    v
Deploy Workflow Package
```

## Demo Mode

The frontend includes a demo mode for reliable walkthroughs:

1. Open the app.
2. Click **Load Demo Workflow**.
3. Watch API discovery, DAG construction, code streaming, self-debug, and deployment events replay through the UI.

## Real Integrations

ForgeFlow generates code that makes real API calls when credentials are configured.

| Service | Auth Method | Capabilities |
|---------|-------------|--------------|
| Slack | Bot Token | Send messages, create channels, invite users, lookup users, upload files |
| Gmail | SMTP App Password | Send plain-text or HTML emails |
| Google Sheets | API Key | Read ranges, append rows, update values |
| HTTP/Webhooks | URL/API token | Monitor URLs and call REST endpoints |

Services without configured credentials are skipped gracefully in generated workflows instead of crashing.

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

## Tech Stack

| Component | Technology |
|-----------|------------|
| AI Pipeline | LangGraph |
| LLM | Google Gemini 2.5 Flash |
| Embeddings | Gemini Embedding 001 |
| Vector Store | ChromaDB |
| Backend | FastAPI + WebSocket |
| Frontend | React + Vite + React Flow + Tailwind CSS |
| Sandbox | Docker primary, AST validation fallback |
| Slack Bot | Slack Bolt Socket Mode |

## Project Structure

```
backend/
  main.py                # FastAPI app, REST API, WebSocket API
  graph.py               # LangGraph workflow generation pipeline
  conversation/          # Requirement extraction and clarification
  discovery/             # API specs, vector store, API selection
  planner/               # DAG building and data mapping
  codegen/               # Gemini code generation, tests, security review
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
```

## Environment Variables

```env
GEMINI_API_KEY=your_gemini_api_key

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
```

`FORGEFLOW_ADMIN_TOKEN` is required for endpoints that execute generated workflow code unless `FORGEFLOW_ALLOW_UNAUTH_DANGEROUS=1` is explicitly set for local demos.

## License

MIT
