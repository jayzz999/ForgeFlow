# ForgeFlow — AI Workflow Generator

> Describe a business workflow in plain English. ForgeFlow discovers APIs, builds a DAG, generates executable code, self-debugs on failure, and deploys — all autonomously.


---

## What Makes ForgeFlow Different

Most automation tools (Zapier, n8n, Make) let you **connect** pre-built blocks. ForgeFlow **generates** the entire workflow from scratch using a 10-node AI pipeline:

| Layer | Component | What It Does |
|-------|-----------|-------------|
| 1 | Conversation Engine | Extracts structured requirements from natural language, asks clarifying questions when details are missing |
| 2 | Semantic API Discovery | Finds the right APIs from 18 endpoints across 5 services using ChromaDB vector similarity search |
| 3 | DAG Planner | Builds an execution graph with dependency resolution, parallel groups, and data flow mapping |
| 4 | Code Generator | Gemini-powered tool-calling agent that browses API docs, tests endpoints, and writes production Python |
| 5 | Security Review | Scans generated code for unsafe patterns (eval, hardcoded secrets, shell injection) |
| 6 | Sandbox Execution | Runs code in Docker containers with real credentials and dependency installation |
| 7 | Self-Debugger | Diagnoses failures (IMPORT_ERROR, AUTH_FAILURE, etc.), patches code, and retries up to 3 times |
| 8 | Deployment | Packages workflow with Dockerfile, docker-compose, k8s manifests, Makefile, and README |

---

## Quick Start

```bash
# 1. Clone and enter project
git clone https://github.com/your-org/ForgeFlow.git
cd ForgeFlow

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys (at minimum: GEMINI_API_KEY)

# 4. Start the backend
python -m backend.main

# 5. In a new terminal — start the frontend
cd frontend && npm install && npm run dev
```

Open **http://localhost:3000** and start forging workflows.

---

## Real Integrations

ForgeFlow generates code that makes **real API calls** — not mock responses. Currently integrated:

| Service | Auth Method | Capabilities |
|---------|-------------|-------------|
| Slack | Bot Token (OAuth) | Send messages, create channels, invite users, lookup users, upload files |
| Gmail | SMTP (App Password) | Send emails with plain text or HTML body |
| Google Sheets | API Key | Read ranges, append rows, update values |

The pipeline is credential-aware: services without configured credentials are skipped gracefully with a warning instead of crashing.

---

## Clarification Flow

When a request is vague (e.g. "automate employee onboarding"), ForgeFlow asks targeted clarifying questions before generating code:

```
User: "automate employee onboarding"

ForgeFlow: "I'd like to clarify a few things to generate a better workflow."
  1. What Slack channel should the welcome message be sent to?
  2. What email address should receive the onboarding checklist?
```

The frontend renders an interactive clarification card. Once answered, the pipeline restarts with the combined context.

---

## Demo Mode

For reliable live demos without API latency risk:

1. Open the app
2. Click **"Load Demo Workflow"**
3. Watch the full pipeline replay with cinematic timing:
   - API discovery with animated badges
   - DAG construction with React Flow
   - Code streaming with syntax highlighting
   - Self-debug cycle (failure, diagnosis, fix, retry, success)
   - Confetti celebration on deploy

---

## Architecture

```
User Request (Natural Language)
        |
        v
+---------------------+     Confidence < 0.75?
| Conversation Engine |----> Ask Clarifying Questions ---> User Responds
+---------------------+                                        |
        |  (confidence >= 0.75)                                |
        v                                                      v
+---------------------+                              (re-enter pipeline)
| API Discovery       | -- ChromaDB vector search across 18 endpoints
+---------------------+
        |
        v
+---------------------+
| DAG Planner         | -- Build execution graph + data flow mappings
+---------------------+
        |
        v
+---------------------+
| Code Generator      | -- Gemini tool-calling agent (browse docs, test APIs, write code)
+---------------------+
        |
        v
+---------------------+
| Security Review     | -- Scan for unsafe patterns
+---------------------+
        |
        v
+---------------------+
| Test Generator      | -- Auto-generate pytest tests
+---------------------+
        |
        v
+---------------------+     +---------------------+
| Sandbox Execute     |---->| Self-Debug Loop     |
| (Docker / AST)      |<----| (diagnose + patch)  |
+---------------------+     +---------------------+
        |                          (max 3 retries)
        v
+---------------------+
| Deploy              | -- Package + Slack notification
+---------------------+
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| AI Pipeline | LangGraph (10-node stateful agent graph) |
| LLM | Google Gemini 2.5 Flash (tool-calling agent with 5 tools) |
| Embeddings | Gemini Embedding 001 |
| Vector Store | ChromaDB |
| Backend | FastAPI + WebSocket |
| Frontend | React + Vite + React Flow + Tailwind CSS |
| Real-time | WebSocket event streaming with auto-reconnect |
| Sandbox | Docker (primary) + AST validation (fallback) |
| Slack Bot | Slack Bolt (Socket Mode) for real-time notifications |

---

## Project Structure

```
ForgeFlow/
  backend/
    main.py               # FastAPI + WebSocket server + Slack bot startup
    graph.py              # LangGraph pipeline (10 nodes, conditional edges)
    conversation/
      engine.py           # Intent extraction + clarification logic
    discovery/
      api_selector.py     # ChromaDB vector search for API matching
      specs/              # API specifications (Slack, Gmail, Sheets, Deriv)
    planner/
      dag_builder.py      # Workflow DAG construction
      data_mapper.py      # Inter-step data flow mapping
    codegen/
      generator.py        # Gemini tool-calling agent for code generation
      security.py         # Security pattern scanner
    execution/
      sandbox.py          # Code execution orchestrator (Docker + AST)
      docker_sandbox.py   # Docker container execution with env vars
      self_debugger.py    # Error diagnosis + code patching
    modifier/
      engine.py           # Natural language workflow modification
    slack/
      bot.py              # Slack bot (Socket Mode)
      notifications.py    # Pipeline event -> Slack notifications
    tools/
      definitions.py      # Tool schemas for Gemini agent
      executor.py         # Tool execution (fetch_web_page, write_file, etc.)
    shared/
      config.py           # Environment config (dotenv)
      models.py           # Pydantic models (WorkflowDAG, WorkflowStep, etc.)
      gemini_client.py    # Gemini API wrapper (text, JSON, tool-calling)
  frontend/
    src/
      App.jsx             # Main layout + celebration overlay
      hooks/
        useWebSocket.js   # WebSocket with auto-reconnect + timeout recovery
      components/
        ChatPanel.jsx     # Chat input + demo button + clarification cards
        WorkflowCanvas.jsx # React Flow DAG with animated nodes
        CodePanel.jsx     # Syntax-highlighted code with streaming effect
        StatusBar.jsx     # Pipeline phase indicator
        ApiDiscoveryBadge.jsx # Animated API service badges
        DebugOverlay.jsx  # Self-debug diagnosis display
  workflows/              # Deployed workflow packages (auto-generated)
  tests/                  # Test suite
```

---

## Environment Variables

```env
# Required
GEMINI_API_KEY=your_gemini_api_key

# Slack (real integration)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_NOTIFICATION_CHANNEL=#your-channel

# Gmail SMTP (real integration)
GMAIL_ADDRESS=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password

# Google Sheets (real integration)
GOOGLE_API_KEY=your-api-key
GOOGLE_SHEET_ID=your-spreadsheet-id

# Pipeline config
GEMINI_MODEL=gemini-2.5-flash
MAX_DEBUG_ATTEMPTS=3
SANDBOX_TIMEOUT=60
```

---

## How It Works — End to End

1. **User types**: "Send a welcome message to #deriv on Slack saying Hello from ForgeFlow"
2. **Conversation Engine**: Extracts intent, identifies Slack service, confidence 0.85 (above 0.75 threshold)
3. **API Discovery**: Vector search finds `POST /chat.postMessage` from Slack spec (confidence 0.95)
4. **DAG Planner**: Creates 2-step graph: trigger -> send_slack_message
5. **Code Generator**: Gemini agent generates ~280 lines of production Python with httpx, retry logic, error handling
6. **Security Review**: Scans for hardcoded secrets, eval(), shell injection — passes
7. **Sandbox Execute**: Runs in Docker with `SLACK_BOT_TOKEN` injected — real message appears in Slack
8. **Deploy**: Packages into `workflows/{id}/` with Dockerfile, docker-compose.yml, k8s manifest, Makefile, README

---

## License

MIT
