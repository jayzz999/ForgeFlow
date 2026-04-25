# ForgeFlow — Project Report

## Deriv AI Talent Sprint Hackathon | February 7-8, 2026

---

## 1. Executive Summary

ForgeFlow is an AI-powered workflow automation engine that converts plain English descriptions into fully deployed, production-quality Python applications. Unlike traditional automation platforms such as Zapier, n8n, or Make that require users to manually connect pre-built blocks, ForgeFlow autonomously discovers APIs, builds execution graphs, generates real code, tests it in a sandbox, self-debugs on failure, and deploys — all from a single natural language prompt.

The system is built around a 10-node LangGraph pipeline powered by Google Gemini 2.5 Flash, with real integrations to Slack, Gmail, Google Sheets, and Deriv's trading APIs. The React frontend provides real-time WebSocket streaming of every pipeline stage with animated visualizations.

**Key Metrics:**
- 50 Python source files | 8,096 lines of backend code
- 10 frontend components | 1,687 lines of React/JS/CSS
- 18 indexed API endpoints across 5 services
- 10-node stateful AI pipeline with conditional routing
- End-to-end workflow generation in under 60 seconds

---

## 2. Problem Statement

### The Gap in Workflow Automation

Enterprise workflow automation is a $13B+ market, yet building custom integrations remains painful:

- **Low-code tools** (Zapier, Make) offer pre-built connectors but lack flexibility for custom logic, complex data transformations, or novel APIs.
- **Code-based approaches** require developers to write hundreds of lines of integration code for each workflow, dealing with authentication, error handling, retries, and deployment.
- **AI code generators** (Copilot, Cursor) assist developers but don't understand the full lifecycle — they generate code snippets, not complete deployed systems.

### Our Insight

What if an AI system could handle the entire lifecycle — from understanding what the user wants, to discovering which APIs to use, to generating production-quality code, to testing and deploying it — all autonomously?

---

## 3. Solution: ForgeFlow

ForgeFlow bridges the gap between "describe what you want" and "here's your deployed automation" using a multi-stage AI pipeline. Each stage is specialized for a specific task, creating a system that is greater than the sum of its parts.

### Core Capabilities

1. **Natural Language Understanding**: Extracts structured business requirements from vague English descriptions. Asks clarifying questions when details are missing.

2. **Semantic API Discovery**: Uses vector similarity search to match user intent to real API endpoints from an indexed knowledge base of 18 endpoints across 5 services.

3. **Autonomous Code Generation**: A Gemini tool-calling agent with 5 tools that can browse API documentation, test endpoints, execute shell commands, and write multi-file projects — not just generate code, but research and validate it.

4. **Self-Debugging Loop**: If generated code fails in the sandbox, ForgeFlow diagnoses the root cause (import errors, auth failures, API errors, timeouts), patches the code, and retries up to 3 times.

5. **Production Deployment**: Successfully tested code is packaged with Dockerfile, docker-compose.yml, Kubernetes manifests, Makefile, requirements.txt, and README.

6. **Real Integrations**: Every generated workflow makes real API calls — real Slack messages, real emails, real spreadsheet updates.

---

## 4. Technical Architecture

### 4.1 System Overview

```
User Request (Natural Language)
        |
        v
+---------------------+     Confidence < 0.75?
| Conversation Engine |----> Ask Clarifying Questions --> User Responds
+---------------------+                                       |
        |  (confidence >= 0.75)                               |
        v                                                     v
+---------------------+                            (re-enter pipeline)
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
| Code Generator      | -- Gemini tool-calling agent (5 tools, 15 rounds max)
+---------------------+
        |
        v
+---------------------+
| Security Review     | -- AST-based scan for unsafe patterns
+---------------------+
        |
        v
+---------------------+
| Test Generator      | -- Auto-generate pytest test suite
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
| Deploy + Notify     | -- Package + Slack notification
+---------------------+
```

### 4.2 The 10-Node LangGraph Pipeline

ForgeFlow uses LangGraph to orchestrate a stateful, multi-step agent graph. Each node is a specialized async function that reads from and writes to a shared state dictionary.

| Node | Name | Function |
|------|------|----------|
| 1 | `conversation_node` | Extracts intent, entities, actions, and confidence score from user input using Gemini |
| 2 | `api_discovery_node` | Performs semantic search over ChromaDB to find matching API endpoints |
| 3 | `plan_workflow_node` | Builds a directed acyclic graph (DAG) with dependency resolution and parallel execution groups |
| 4 | `generate_code_node` | Runs Gemini tool-calling agent to produce complete Python code |
| 5 | `review_security_node` | Scans code AST for dangerous patterns (eval, exec, hardcoded secrets, shell injection) |
| 6 | `generate_tests_node` | Creates pytest test suite for the generated workflow |
| 7 | `sandbox_execute_node` | Executes code in Docker container with real credentials |
| 8 | `self_debug_node` | Diagnoses execution failures and patches code |
| 9 | `present_to_user_node` | Formats results for frontend display |
| 10 | `deploy_node` | Packages workflow into deployable project with infrastructure files |

**Conditional Edges:**
- After `conversation_node`: Routes to `api_discovery_node` if confidence >= 0.75, otherwise returns clarification questions to the user
- After `sandbox_execute_node`: Routes to `self_debug_node` if execution fails and debug attempts < 3, otherwise proceeds to deployment
- After `self_debug_node`: Loops back to `sandbox_execute_node` for re-execution

### 4.3 Conversation Engine & Clarification Flow

The conversation engine uses Gemini to analyze user requests and produce structured output:

```json
{
  "workflow_name": "Employee Onboarding Automation",
  "description": "...",
  "confidence": 0.5,
  "actions": [
    {"id": "send_welcome", "service_hint": "Slack", "description": "..."},
    {"id": "send_email", "service_hint": "Gmail", "description": "..."}
  ],
  "clarification_needed": [
    "Which Slack channel should the welcome message be sent to?",
    "What email address should receive the onboarding checklist?"
  ]
}
```

**Confidence Scoring:**
- 0.9+ = Clear intent with ALL specifics (channel names, emails, exact messages)
- 0.7-0.89 = Clear intent with MOST specifics
- 0.5-0.69 = Clear intent but missing specifics (triggers clarification)
- Below 0.5 = Unclear intent

When confidence is below 0.75, the pipeline stops and sends clarification questions to the frontend via WebSocket. The user's answers are combined with the original request and the pipeline restarts.

### 4.4 Semantic API Discovery

ForgeFlow uses ChromaDB with Gemini Embedding 001 to index API specifications. Each endpoint is stored as a vector embedding of its description, parameters, and capabilities.

**Indexed Services (18 endpoints):**

| Service | Endpoints | Auth Method |
|---------|-----------|-------------|
| Slack Web API | chat.postMessage, conversations.create, conversations.invite, users.lookupByEmail, files.upload, reactions.add | Bearer Token |
| Gmail SMTP | send | App Password |
| Google Sheets API v4 | values.get, values.append, values.update, spreadsheets.create | API Key |
| Deriv Trading API | ticks, proposal, buy, active_symbols | WebSocket + Token |
| Deriv Account API | balance, statement, profit_table | WebSocket + Token |

When a user requests an action like "send a message to Slack", the discovery engine:
1. Converts the action description to a vector embedding
2. Performs cosine similarity search against indexed endpoints
3. Returns the best match with a confidence score
4. For unmatched actions, flags them for the code generator's research tools

### 4.5 Code Generator — The Tool-Calling Agent

The code generator is not a simple prompt-and-respond system. It's a Gemini tool-calling agent with 5 tools that iterates up to 15 rounds:

| Tool | Purpose |
|------|---------|
| `fetch_web_page` | Browse API documentation, READMEs, code examples from any URL |
| `execute_shell` | Run shell commands to test snippets, validate syntax, check environment |
| `write_file` | Create additional project files (config.py, clients, Dockerfile, tests) |
| `read_file` | Read back previously written files for review |
| `test_api_endpoint` | Make real HTTP requests to verify API availability and response format |

**Credential Awareness:** The generator receives a list of which services have real credentials configured. For configured services, it generates full integration code. For unconfigured services, it generates the integration but adds graceful skip logic.

**Pre-Built Patterns:** The system prompt includes production-tested code patterns for each service (Slack httpx, Gmail SMTP, Sheets API, Deriv WebSocket) with retry logic, error handling, and proper auth headers.

**Output:** Complete Python files with:
- Async/await with httpx.AsyncClient for all HTTP calls
- Environment variables for all secrets
- Retry with exponential backoff (max 3 retries per API call)
- Structured logging with timestamps
- asyncio.gather() for parallel steps
- Summary report at the end

### 4.6 Security Review

The security reviewer performs AST-based static analysis on generated code, checking for:

- `eval()` / `exec()` calls
- Hardcoded API keys or tokens
- Shell command injection via `subprocess` or `os.system`
- Unsafe file operations
- Network calls to suspicious domains

Each finding is categorized by severity (critical/warning/info) and reported to the user.

### 4.7 Sandbox Execution

ForgeFlow supports two execution modes:

**Docker Sandbox (Primary):**
- Runs code in a `python:3.12-slim` container
- Injects environment variables with matching prefixes (SLACK_, GMAIL_, GOOGLE_, DERIV_)
- Installs dependencies (httpx, websockets, aiohttp) via a generated `run.sh`
- Passes extra project files into the container
- 60-second timeout
- Network access enabled for real API calls

**AST Validation (Fallback):**
- Pure in-process Python AST parsing
- Validates syntax, checks for main() function, counts functions/classes
- Checks for real API integration vs placeholders
- Always passes for syntactically valid code (by design — the focus is on code quality, not execution simulation)

### 4.8 Self-Debugging Loop

When sandbox execution fails, the self-debugger:

1. **Parses the error** into a category: IMPORT_ERROR, AUTH_FAILURE, API_ERROR, TIMEOUT, RUNTIME_ERROR, SYNTAX_ERROR
2. **Sends to Gemini** with the original code, error output, and error category
3. **Receives a diagnosis** with root cause analysis and patched code
4. **Returns patched code** for re-execution

This loop runs up to 3 times. The max_tokens for the debugger response is set to 8192 to ensure complete code is returned without truncation.

### 4.9 Deployment Package

Successfully tested workflows are deployed as complete project packages:

```
workflows/{workflow_id}/
  workflow.py          # Main executable code
  requirements.txt     # Python dependencies
  Dockerfile           # Container build file
  docker-compose.yml   # Compose configuration
  k8s-deployment.yaml  # Kubernetes manifest
  Makefile             # Build/run/deploy commands
  run.sh               # Quick start script
  .env.example         # Required environment variables
  README.md            # Auto-generated documentation
  dag.json             # Workflow DAG definition
  test_workflow.py     # Auto-generated tests
```

### 4.10 Real-Time Frontend

The React frontend provides:

- **Chat Interface**: Natural language input with clarification card rendering
- **Workflow Canvas**: React Flow-based DAG visualization with animated nodes
- **Code Panel**: Syntax-highlighted code display with streaming effect
- **Status Bar**: Real-time pipeline phase indicator
- **API Discovery Badges**: Animated service badges showing discovered APIs
- **Debug Overlay**: Self-debug diagnosis and fix display
- **Celebration**: Confetti animation on successful deployment

**WebSocket Protocol:** The frontend connects via `ws://host/ws/{clientId}` and receives typed events for each pipeline stage. Events include phase information, progress data, and results. Auto-reconnect with exponential backoff handles connection drops.

---

## 5. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| AI Orchestration | LangGraph 0.2.60 | Stateful multi-node agent graph |
| LLM | Google Gemini 2.5 Flash | Text generation, tool calling, JSON output |
| Embeddings | Gemini Embedding 001 | Semantic vector representations |
| Vector Store | ChromaDB 0.5.23 | In-memory vector similarity search |
| Backend | FastAPI 0.115.6 | REST API + WebSocket server |
| ASGI Server | Uvicorn 0.34.0 | High-performance async server |
| HTTP Client | httpx 0.28.1 | Async HTTP for generated code |
| Slack SDK | slack-bolt 1.21.3 | Real-time Slack bot (Socket Mode) |
| Frontend | React 18.3 | Component-based UI |
| Build Tool | Vite 6.0.5 | Fast frontend builds |
| Styling | Tailwind CSS 3.4.17 | Utility-first CSS |
| DAG Visualization | @xyflow/react 12.3.6 | Interactive graph rendering |
| Code Highlighting | react-syntax-highlighter | Syntax-highlighted code display |
| Containerization | Docker | Sandbox execution + deployment |
| Data Validation | Pydantic 2.10.4 | Type-safe models |
| Web Parsing | BeautifulSoup4 + lxml | HTML parsing for agent's web browsing |

---

## 6. API Integrations Detail

### 6.1 Slack (Real — Working)
- **Auth**: Bot Token (xoxb-) via OAuth
- **Transport**: HTTPS REST API
- **Capabilities**: Send messages, create channels, invite users, lookup users by email, upload files, add reactions
- **Bot Features**: Socket Mode real-time event handling, pipeline notifications to configured channel

### 6.2 Gmail (Real — SMTP)
- **Auth**: Gmail App Password (not OAuth)
- **Transport**: SMTP via Python's built-in smtplib
- **Capabilities**: Send plain text and HTML emails
- **Design Choice**: SMTP with App Password was chosen over Gmail API OAuth for simplicity — no Google Cloud project, no OAuth consent screen, no token refresh logic needed

### 6.3 Google Sheets (Real — API Key)
- **Auth**: Google API Key
- **Transport**: HTTPS REST API (Sheets API v4)
- **Capabilities**: Read ranges, append rows, update values, create spreadsheets
- **Requirement**: Spreadsheet must be shared as "Anyone with the link can edit"

### 6.4 Deriv Trading (Real — WebSocket)
- **Auth**: API Token via WebSocket authorize message
- **Transport**: WebSocket (wss://ws.derivws.com/websockets/v3)
- **Capabilities**: Subscribe to tick streams, get price proposals, buy contracts, list active symbols, check account balance

---

## 7. Key Design Decisions

### 7.1 LangGraph Over Simple Chains
LangGraph's stateful graph model was chosen over LangChain's sequential chains because:
- Conditional routing (clarification vs. proceed) requires branching
- The self-debug loop requires cycles in the graph
- State persistence between nodes enables data sharing without globals
- Each node can be tested and debugged independently

### 7.2 Tool-Calling Agent Over One-Shot Generation
The code generator uses a multi-round tool-calling agent (up to 15 rounds) instead of a single prompt because:
- It can research unknown APIs by browsing their documentation
- It can test endpoints before writing code for them
- It can write multi-file projects incrementally
- It can validate its own code using shell execution
- It produces significantly more complete and correct code

### 7.3 SMTP Over Gmail API
Gmail SMTP with App Password was chosen over Gmail API OAuth because:
- Zero setup: no Google Cloud project, no OAuth consent screen, no redirect URIs
- No token refresh logic needed
- Works with Python's built-in smtplib — no extra dependencies
- Sufficient for the hackathon use case (sending emails)

### 7.4 Docker Sandbox with AST Fallback
Docker is the primary execution environment because it provides isolation and real API access. AST validation serves as a fallback when Docker is unavailable, ensuring the pipeline never blocks on execution.

### 7.5 Credential Awareness
Rather than failing when a service lacks credentials, the system:
- Tells the code generator which services are available
- Generated code checks for empty env vars and skips gracefully
- Logs warnings instead of crashing
- This enables partial execution of multi-service workflows

---

## 8. Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Uvicorn restart during code generation — agent's write_file tool triggered WatchFiles | Disabled reload, moved temp directory to /tmp/forgeflow_codegen |
| Sandbox subprocess broke on triple-quoted strings in generated code | Complete rewrite to pure in-process AST validation |
| Self-debugger returned truncated JSON, causing "Unterminated string" errors | Increased max_tokens from 4000 to 8192 |
| Docker container couldn't import project modules | Added extra_files parameter to pass all project files into container |
| Gemini skipped clarification for vague requests | Rewrote confidence scoring rules and examples in system prompt |
| Data mapper hallucinated default values (#general instead of #deriv) | Added explicit instructions to use exact step input values |
| Slack channel_not_found error | Fixed channel configuration and bot membership |

---

## 9. Future Roadmap

1. **More Integrations**: GitHub, Jira, Notion, Discord, Twilio, Stripe
2. **Scheduled Triggers**: Cron-based workflow execution
3. **Webhook Triggers**: HTTP webhook endpoints that start workflows
4. **Workflow Marketplace**: Share and reuse community-created workflows
5. **Visual DAG Editor**: Drag-and-drop modification of generated DAGs
6. **Multi-LLM Support**: Swap between Gemini, GPT-4, Claude for generation
7. **Monitoring Dashboard**: Track workflow execution history and failures
8. **Natural Language Modification**: Modify deployed workflows by describing changes in English (partially implemented)

---

## 10. How to Run

```bash
# Clone
git clone https://github.com/jayzz999/ForgeFlow.git
cd ForgeFlow

# Backend
pip install -r requirements.txt
cp .env.example .env  # Add your API keys
python -m backend.main

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 and describe any workflow in plain English.

---

## 11. Team

Built for the Deriv AI Talent Sprint Hackathon (February 7-8, 2026).

**Repository**: https://github.com/jayzz999/ForgeFlow

---

*This report was generated for the ForgeFlow project submission.*
