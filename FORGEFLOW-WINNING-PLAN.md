# FORGEFLOW: The Deepest AI Workflow Generator Ever Built
## Deriv AI Talent Sprint — Winning Architecture Plan

**Challenge:** AI-Powered Business Workflow Generator  
**Philosophy:** "Everyone has the same problem statement, but the deepest project wins"  
**Date:** Feb 7-8, 2026

---

## 1. Competitive Landscape — What Exists Today

Before we build, we need to know exactly what we're competing against — not other hackathon teams, but the state of the art. Because if a judge can say "n8n already does this", you've lost.

### What n8n AI Workflow Builder Does (Oct 2025)
- Natural language → selects from its **own node catalog** (pre-built integrations)
- Auto-fills credentials from user's saved credentials
- Auto-connects nodes in logical sequence
- Multi-turn refinement via chat
- **Limitation:** Only works within n8n's ecosystem. Cannot discover arbitrary APIs. Cannot generate executable code. Cannot self-debug. Cloud-only, credit-gated.

### What Zapier AI / Make.com Do
- Template-based: select from pre-built "Zaps" or "Scenarios"
- AI helps configure parameters, not generate workflows
- **Limitation:** Locked to their integration catalog. No code generation. No self-healing.

### What OpenClaw Does
- Personal AI assistant with skill/plugin architecture
- Can chain skills into pipelines via "Lobster" workflow shell
- Discovers and installs skills automatically
- **Limitation:** Developer-focused. Requires CLI. Not for business users. No visual workflow generation. No API discovery from documentation.

### What Dify / Sim Studio Do
- Visual canvas for AI agent workflows
- Copilot generates nodes from natural language
- **Limitation:** AI-agent-focused, not general business workflow generation. No API discovery. No self-debugging.

### THE GAP NOBODY HAS FILLED
No tool today does ALL of these together:
1. Takes plain English business requirements
2. **Discovers the right APIs from actual documentation** (not a pre-built catalog)
3. Generates **executable Python code** (not platform-locked JSON configs)
4. **Self-debugs** when execution fails
5. Allows natural language modifications without rebuilding
6. Shows a visual workflow the business user can understand

**That's ForgeFlow. And that's why it wins.**

---

## 2. Core Innovation — What Makes ForgeFlow "The Deepest"

### The Five Depths

**Depth 1: Conversational Intelligence**
Not just "parse the request" — ForgeFlow conducts a *smart* conversation. It infers missing requirements from context, asks minimal clarifying questions, and builds a mental model of the business process. Most tools either ask too many questions or guess wrong.

**Depth 2: Semantic API Discovery**
This is the hardest unsolved problem in the space. User says "send a welcome email" — ForgeFlow searches a vector store of real API documentation (OpenAPI specs), finds the Gmail API `messages.send` endpoint, understands the required parameters (to, subject, body, auth), and maps them correctly. It does this across multiple systems in a single workflow.

**Depth 3: Intelligent Code Generation**
Not template stitching — actual executable Python code with:
- Proper error handling and retry logic
- Data mapping between API steps (output of step 1 → input of step 2)
- Input validation and type checking
- Configurable via environment variables
- Audit logging built in

**Depth 4: Self-Debugging Loop**
Workflow fails → ForgeFlow reads the traceback → diagnoses the root cause → generates a fix → re-executes → verifies success. This runs up to 3 iterations automatically. This is the "blow their minds" feature from the challenge doc.

**Depth 5: Living Workflow**
Natural language modifications after generation: "Add a 2-day delay before the training email" → ForgeFlow modifies the existing workflow DAG and regenerates only the affected code, preserving everything else.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FORGEFLOW                                 │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   CONVERSATION ENGINE                        │ │
│  │  ┌──────────┐  ┌──────────────┐  ┌─────────────────────┐   │ │
│  │  │ Chat UI   │  │ Intent       │  │ Requirement         │   │ │
│  │  │ (React)   │──│ Classifier   │──│ Extractor +         │   │ │
│  │  │           │  │ (LLM)        │  │ Clarifier (LLM)     │   │ │
│  │  └──────────┘  └──────────────┘  └──────┬──────────────┘   │ │
│  └─────────────────────────────────────────┼───────────────────┘ │
│                                             │                     │
│                                             ▼                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   WORKFLOW PLANNER                            │ │
│  │  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐   │ │
│  │  │ DAG Builder   │  │ API         │  │ Data Flow        │   │ │
│  │  │ (LLM +        │──│ Discovery   │──│ Mapper           │   │ │
│  │  │  Structured)  │  │ (RAG)       │  │ (LLM)            │   │ │
│  │  └──────────────┘  └─────────────┘  └──────┬───────────┘   │ │
│  └─────────────────────────────────────────────┼───────────────┘ │
│                                                 │                 │
│                                                 ▼                 │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   CODE ENGINE                                │ │
│  │  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐   │ │
│  │  │ Code          │  │ Security    │  │ Sandbox          │   │ │
│  │  │ Generator     │──│ Reviewer    │──│ Executor         │   │ │
│  │  │ (LLM)         │  │ (Static +   │  │ (Docker)         │   │ │
│  │  │               │  │  LLM)       │  │                  │   │ │
│  │  └──────────────┘  └─────────────┘  └──────┬───────────┘   │ │
│  └─────────────────────────────────────────────┼───────────────┘ │
│                                                 │                 │
│                                          ┌──────┴──────┐         │
│                                          │  PASS/FAIL?  │         │
│                                          └──────┬──────┘         │
│                                     ┌───────────┴───────────┐   │
│                                     ▼                       ▼   │
│                              ┌─────────────┐        ┌──────────┐│
│                              │ SELF-DEBUG   │        │ DEPLOY + ││
│                              │ LOOP         │        │ APPROVE  ││
│                              │ (max 3x)     │        │          ││
│                              └─────────────┘        └──────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   SHARED LAYER                               │ │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │ API Spec  │ │ Audit    │ │ Workflow │ │ WebSocket    │  │ │
│  │  │ Vector DB │ │ Logger   │ │ Store    │ │ Events       │  │ │
│  │  │ (Chroma)  │ │ (SQLite) │ │ (SQLite) │ │ (FastAPI)    │  │ │
│  │  └───────────┘ └──────────┘ └──────────┘ └──────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Deep Dive: Each Component

### 4.1 Conversation Engine (LangGraph)

This is NOT a simple prompt-in/code-out system. The conversation engine conducts a structured dialogue that feels natural.

**LangGraph State:**
```python
class ConversationState(TypedDict):
    messages: List[dict]              # Full conversation history
    business_requirements: dict       # Extracted structured requirements
    clarification_needed: List[str]   # Questions still unanswered
    workflow_intent: str              # High-level intent classification
    entities: List[dict]              # Systems, actions, data mentioned
    confidence: float                 # How complete are requirements
    phase: str                        # "collecting" | "confirming" | "building"
```

**Smart Clarification Strategy:**
The key insight: business users hate being interrogated. ForgeFlow uses a **confidence threshold** approach:
- Extract everything possible from the initial request
- Only ask about HIGH-IMPACT missing info (auth, critical data flows, error behavior)
- For LOW-IMPACT gaps, use sensible defaults and tell the user what was assumed
- Maximum 2 clarifying questions before showing a plan

**Example Conversation Flow:**
```
USER: "When someone submits a support ticket in Jira, I want to 
       classify it by urgency using AI, assign it to the right team, 
       and send a Slack notification to the team channel"

FORGEFLOW: I'll build a workflow that:
  1. Watches for new Jira tickets (webhook trigger)
  2. Uses AI to classify urgency (Critical/High/Medium/Low)  
  3. Routes to the appropriate team based on classification
  4. Sends a formatted Slack message to the team's channel

Quick question: Should I map specific teams to urgency levels 
(e.g., Critical → Platform team, High → Backend team), or should 
the AI also determine the team from the ticket content?

USER: "AI should determine the team from content"

FORGEFLOW: Got it. Here's the workflow plan:
  [Shows visual DAG]
  Shall I generate this? You can modify it after.
```

### 4.2 Semantic API Discovery Engine (THE KEY DIFFERENTIATOR)

This is what nobody else has built properly. It's the hardest part and the most impressive.

**Architecture:**
```
┌───────────────────────────────────────────┐
│           API KNOWLEDGE BASE               │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │     Vector Store (ChromaDB)          │   │
│  │                                       │   │
│  │  Collection: api_endpoints            │   │
│  │  ┌─────────────────────────────────┐ │   │
│  │  │ Each document =                  │ │   │
│  │  │   - API name (e.g., "Gmail")     │ │   │
│  │  │   - Endpoint path                │ │   │
│  │  │   - HTTP method                  │ │   │
│  │  │   - Natural language description │ │   │
│  │  │   - Required parameters          │ │   │
│  │  │   - Auth type                    │ │   │
│  │  │   - Request/response schema      │ │   │
│  │  │   - Code example                 │ │   │
│  │  └─────────────────────────────────┘ │   │
│  │                                       │   │
│  │  Collection: api_auth_patterns        │   │
│  │  ┌─────────────────────────────────┐ │   │
│  │  │  OAuth2, API Key, Bearer Token  │ │   │
│  │  │  per service                     │ │   │
│  │  └─────────────────────────────────┘ │   │
│  │                                       │   │
│  │  Collection: data_schemas             │   │
│  │  ┌─────────────────────────────────┐ │   │
│  │  │  Input/output schemas per       │ │   │
│  │  │  endpoint for data mapping      │ │   │
│  │  └─────────────────────────────────┘ │   │
│  └─────────────────────────────────────┘   │
└───────────────────────────────────────────┘
```

**Pre-loaded API Specs (real OpenAPI docs, chunked and embedded):**
For the hackathon demo, pre-load these commonly-used APIs:
- **Communication:** Gmail API, Slack API, SendGrid, Twilio
- **Project Management:** Jira, Asana, Trello, Linear
- **CRM:** HubSpot, Salesforce (key endpoints)
- **HR/Identity:** BambooHR (or mock HR system)
- **Data:** Google Sheets, Airtable, PostgreSQL
- **Finance/Trading:** Deriv API (WebSocket endpoints for trading, account management, market data) ← **Critical for Deriv judges**
- **Cloud:** AWS S3, basic cloud ops

**How Discovery Works:**
```python
async def discover_apis(self, user_intent: str, step_description: str) -> List[APIEndpoint]:
    """
    User says: "send a welcome email"
    1. Embed the intent: "send a welcome email to new employee"
    2. Search vector store for semantically similar API endpoints
    3. Return top-k matches with confidence scores
    4. LLM selects the best match and extracts required params
    """
    # Step 1: Semantic search
    results = self.vector_store.similarity_search(
        query=f"{user_intent}: {step_description}",
        k=5,
        collection="api_endpoints"
    )
    
    # Step 2: LLM reranks and selects
    selection = await self.llm.select_best_api(
        intent=step_description,
        candidates=results,
        context=self.workflow_context
    )
    
    # Step 3: Pull auth pattern
    auth = self.vector_store.get(
        collection="api_auth_patterns",
        filter={"service": selection.service_name}
    )
    
    return APIEndpoint(
        service=selection.service_name,
        endpoint=selection.endpoint,
        method=selection.method,
        params=selection.required_params,
        auth_type=auth.type,
        code_example=selection.code_example
    )
```

**WHY THIS IS HARD AND WHY IT IMPRESSES:**
- n8n: pre-built 500+ nodes, no discovery needed
- Zapier: pre-built 7000+ integrations, no discovery needed
- ForgeFlow: discovers APIs from **documentation**, not from a pre-built catalog. 
  This means it can theoretically work with ANY API if you add its OpenAPI spec.
  The judge question "What happens when a required API doesn't exist?" has 
  an answer: "Add the OpenAPI spec to the knowledge base."

### 4.3 Workflow Planner (DAG Generation)

Takes structured requirements + discovered APIs → generates an executable DAG.

**DAG Schema:**
```python
class WorkflowStep(BaseModel):
    id: str                          # step_1, step_2, etc.
    name: str                        # Human-readable: "Send Welcome Email"
    description: str                 # What this step does
    api: APIEndpoint                 # Discovered API details
    inputs: dict                     # Where each input comes from
    outputs: dict                    # What this step produces
    depends_on: List[str]            # Step IDs this depends on
    error_handling: str              # "retry_3x" | "fallback" | "abort"
    condition: Optional[str]         # Conditional execution logic

class WorkflowDAG(BaseModel):
    id: str
    name: str
    description: str
    trigger: dict                    # What starts this workflow
    steps: List[WorkflowStep]
    global_error_handler: str
    environment_vars: List[str]      # Required env vars (API keys etc.)
```

**Data Flow Mapping — The Hard Problem:**
The LLM must figure out: "The output of `create_jira_ticket` returns `{"id": "TICKET-123", "key": "PROJ-456"}`. The next step `send_slack_notification` needs a `message` field. Map `key` from step 1 into a formatted message for step 2."

```python
async def map_data_flow(self, source_step: WorkflowStep, target_step: WorkflowStep) -> dict:
    """LLM-powered data mapping between workflow steps"""
    mapping = await self.llm.invoke(
        f"""Given:
        Source step: {source_step.name}
        Source output schema: {source_step.api.response_schema}
        
        Target step: {target_step.name}
        Target input schema: {target_step.api.request_schema}
        
        Generate the data mapping as a Python dict comprehension.
        Map source fields to target fields logically.
        Include any string formatting needed.
        
        Return ONLY valid Python code for the mapping."""
    )
    return mapping
```

### 4.4 Code Generator

Generates **real, executable Python** — not pseudocode, not config files.

**Generated Code Structure:**
```python
# Auto-generated by ForgeFlow
# Workflow: Employee Onboarding Automation
# Generated: 2026-02-07T14:30:00Z

import os
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("forgeflow.workflow")

# ============ CONFIGURATION ============
GMAIL_CREDENTIALS = os.getenv("GMAIL_CREDENTIALS_PATH")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")

# ============ STEP FUNCTIONS ============

async def step_1_send_welcome_email(context: dict) -> dict:
    """Send welcome email to new employee via Gmail API"""
    # ... actual Gmail API call with error handling ...
    
async def step_2_create_slack_account(context: dict) -> dict:
    """Create Slack account and add to channels"""
    # ... actual Slack API call ...

async def step_3_create_jira_onboarding(context: dict) -> dict:
    """Create Jira ticket for IT setup"""
    # ... actual Jira API call ...

# ============ ORCHESTRATOR ============

async def run_workflow(trigger_data: dict):
    """Main workflow orchestrator with error handling"""
    context = {"trigger": trigger_data, "results": {}}
    
    try:
        # Step 1: Send welcome email
        result_1 = await step_1_send_welcome_email(context)
        context["results"]["step_1"] = result_1
        logger.info(f"Step 1 completed: {result_1['status']}")
        
        # Steps 2 & 3 can run in parallel (no dependency)
        result_2, result_3 = await asyncio.gather(
            step_2_create_slack_account(context),
            step_3_create_jira_onboarding(context),
            return_exceptions=True
        )
        # ... error handling for each ...
        
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        await notify_error(context, e)
        raise

    return context
```

**What makes the generated code special:**
- Parallel execution where dependencies allow (not just sequential)
- Per-step error handling with retry logic
- Proper async/await patterns
- Environment variable configuration (no hardcoded secrets)
- Structured logging for debugging
- Type hints for maintainability

### 4.5 Self-Debugging Loop (THE SHOWSTOPPER)

This is the feature the challenge doc explicitly says would "blow their minds."

```
┌─────────────────────────────────────────────────┐
│              SELF-DEBUG LOOP                      │
│                                                   │
│  Execute in Sandbox                               │
│       │                                           │
│       ├── SUCCESS → Deploy                        │
│       │                                           │
│       └── FAILURE                                 │
│            │                                      │
│            ▼                                      │
│  ┌─────────────────────┐                          │
│  │ Error Analyzer (LLM) │                         │
│  │                       │                         │
│  │ Reads:                │                         │
│  │ • Full traceback      │                         │
│  │ • Generated code      │                         │
│  │ • API response codes  │                         │
│  │ • Environment state   │                         │
│  │                       │                         │
│  │ Diagnoses:            │                         │
│  │ • Auth error → fix    │                         │
│  │   credentials setup   │                         │
│  │ • Schema mismatch →   │                         │
│  │   fix data mapping    │                         │
│  │ • Rate limit → add    │                         │
│  │   backoff logic       │                         │
│  │ • Missing param →     │                         │
│  │   add required field  │                         │
│  └──────────┬────────────┘                         │
│              │                                      │
│              ▼                                      │
│  ┌─────────────────────┐                           │
│  │ Code Patcher (LLM)   │                          │
│  │                       │                          │
│  │ Generates targeted    │                          │
│  │ fix (not full regen)  │                          │
│  │                       │                          │
│  │ Shows diff to user    │                          │
│  └──────────┬────────────┘                          │
│              │                                       │
│              ▼                                       │
│  Re-execute (attempt 2/3)                            │
│                                                      │
│  After 3 failures → Surface to user with             │
│  diagnosis + suggested manual fix                    │
└─────────────────────────────────────────────────────┘
```

**Implementation:**
```python
async def self_debug(self, code: str, error: Exception, attempt: int) -> str:
    """Analyze failure and generate targeted fix"""
    
    diagnosis = await self.llm.invoke(f"""
    The following workflow code failed during execution.
    
    CODE:
    {code}
    
    ERROR:
    {traceback.format_exc()}
    
    ATTEMPT: {attempt}/3
    
    Diagnose the root cause. Classify as one of:
    - AUTH_ERROR: Authentication/credentials issue
    - SCHEMA_MISMATCH: API request/response format wrong
    - RATE_LIMIT: API rate limiting
    - MISSING_PARAM: Required parameter not provided
    - LOGIC_ERROR: Code logic issue
    - NETWORK_ERROR: Connectivity issue
    
    Then generate the MINIMAL code fix. Return only the specific 
    function that needs to change, not the entire file.
    """)
    
    # Apply patch
    patched_code = apply_targeted_fix(code, diagnosis.fix)
    
    # Log the debug cycle for audit trail
    await self.audit_log.record({
        "event": "self_debug",
        "attempt": attempt,
        "diagnosis": diagnosis.category,
        "fix_description": diagnosis.explanation,
        "diff": generate_diff(code, patched_code)
    })
    
    return patched_code
```

### 4.6 Natural Language Modification Engine

After a workflow is generated and running, users can modify it conversationally.

```
USER: "Actually, add a 2-day delay before sending the training 
       schedule email"

FORGEFLOW: 
  I'll add a 2-day delay between "Send Welcome Email" (step 1) 
  and "Send Training Schedule" (step 4).
  
  [Shows updated DAG with new delay node highlighted]
  
  Only step 4 timing changes. Steps 2-3 (Slack + Jira) still 
  run immediately after step 1.
  
  Apply this change?
```

**How it works:**
1. Parse the modification request against the existing DAG
2. Identify which nodes/edges are affected
3. Generate a DAG diff (not full regeneration)
4. Patch only the affected code sections
5. Show the user what changed visually
6. Re-test the modified workflow

---

## 5. Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Orchestration** | LangGraph (Python) | Stateful multi-step agent graphs, checkpointing, Deriv uses it internally |
| **LLM** | GPT-4o (primary) + GPT-4o-mini (fast classification) | Best code generation, fast classification for intent |
| **Vector Store** | ChromaDB (in-process) | Zero-config, fast, perfect for hackathon. No separate server needed |
| **API Specs** | Real OpenAPI 3.0 JSON specs, chunked + embedded | Real data, not mocked. Downloadable from public API docs |
| **Backend** | FastAPI + WebSocket | Async, real-time streaming of generation progress to frontend |
| **Frontend** | React + Tailwind + shadcn/ui | Clean, modern. Visual DAG rendering with react-flow |
| **DAG Visualization** | React Flow | Industry-standard for workflow visualization |
| **Sandbox** | Docker containers (resource-limited) | Isolated execution with timeout |
| **Database** | SQLite | Workflow storage, audit logs, zero-config |
| **Deployment** | Docker Compose | Single command: `docker-compose up` |

---

## 6. The Visual UI — What Judges See

### Main Screen Layout
```
┌──────────────────────────────────────────────────────────┐
│  FORGEFLOW — AI Workflow Generator              [Deploy] │
├──────────────────────────┬───────────────────────────────┤
│                          │                               │
│   CONVERSATION PANEL     │     WORKFLOW CANVAS           │
│                          │                               │
│   [Chat interface]       │   ┌─────┐    ┌─────┐        │
│                          │   │Trig.│───▶│Step1│        │
│   Business user types    │   └─────┘    └──┬──┘        │
│   here in plain English  │                 │            │
│                          │          ┌──────┴─────┐      │
│   ForgeFlow responds     │          ▼            ▼      │
│   with clarifications    │     ┌─────┐      ┌─────┐    │
│   and progress updates   │     │Step2│      │Step3│    │
│                          │     └──┬──┘      └──┬──┘    │
│                          │        └──────┬─────┘        │
│                          │               ▼              │
│                          │          ┌─────┐             │
│                          │          │Step4│             │
│                          │          └─────┘             │
│                          │                               │
│                          ├───────────────────────────────┤
│                          │   CODE PANEL (collapsible)    │
│                          │                               │
│                          │   [Generated Python code]     │
│                          │   [Syntax highlighted]        │
│                          │   [Self-debug diffs shown]    │
│                          │                               │
├──────────────────────────┴───────────────────────────────┤
│  STATUS BAR: ✅ APIs Discovered: 3 │ 🔧 Generating... │ │
│  ⚡ Self-debug attempt 1/3 │ ✅ Tests passed            │
└──────────────────────────────────────────────────────────┘
```

**Key UI Moments for Demo:**
1. **Chat appearing conversationally** — not a wall of text, message-by-message
2. **DAG building node-by-node** — animated, each node appears as the planner adds it
3. **API discovery indicators** — "🔍 Found Gmail API → messages.send" appearing in real time
4. **Code streaming** — generated code appearing line by line (streamed from LLM)
5. **Self-debug animation** — red flash on failed node → diagnosis appearing → green flash on fix
6. **Deploy confirmation** — human clicks approve, status changes to "Live"

---

## 7. Deriv-Specific Angle (CRITICAL FOR WINNING)

Deriv is a derivatives trading platform. Generic "employee onboarding" demos are fine, but a Deriv-specific workflow demo is what gets you the job offer.

### Demo Workflow #1 (Primary): Automated Trading Alert Pipeline
```
USER: "When the Volatility 75 Index moves more than 2% in 5 minutes, 
       send a Slack alert to the trading-alerts channel, log it 
       to Google Sheets, and create a Jira ticket for the risk team 
       to review"

ForgeFlow discovers:
  - Deriv API: ticks subscription (WebSocket) for V75
  - Slack API: chat.postMessage  
  - Google Sheets API: spreadsheets.values.append
  - Jira API: issue creation
  
Generates a workflow with:
  - WebSocket listener for Deriv tick stream
  - Rolling window calculation for 5-min % change
  - Threshold trigger
  - Parallel: Slack + Sheets + Jira
```

**Why this impresses Deriv judges specifically:**
- Shows you understand their product (Volatility Indices are Deriv's proprietary derived markets)
- Shows the API discovery engine works with Deriv's own API docs
- Shows a realistic use case their risk/trading teams would actually use

### Demo Workflow #2 (Backup): Compliance KYC Workflow
```
USER: "When a new client completes registration, verify their 
       identity documents, check against sanctions lists, assign 
       a risk score, and notify compliance team if high-risk"
```
This hits Deriv's Compliance & Risk track and shows ForgeFlow's versatility.

### Pre-loaded API Specs Must Include:
```
deriv_api_specs/
├── deriv_trading.json       # Ticks, proposals, buy/sell contracts
├── deriv_account.json       # Account creation, KYC, balance
├── deriv_market_data.json   # Active symbols, candles, history
```
Download from: https://api.deriv.com/ and https://developers.deriv.com/

---

## 8. LangGraph Implementation

### Full Graph Structure

```python
from langgraph.graph import StateGraph, START, END

class ForgeFlowState(TypedDict):
    # Conversation
    messages: List[dict]
    phase: str  # "collecting" | "planning" | "generating" | "testing" | "debugging" | "deploying"
    
    # Requirements
    business_requirements: dict
    clarifications_asked: int
    confidence: float
    
    # Planning
    workflow_dag: Optional[WorkflowDAG]
    discovered_apis: List[APIEndpoint]
    data_mappings: List[dict]
    
    # Generation
    generated_code: Optional[str]
    security_review: Optional[dict]
    
    # Execution
    execution_result: Optional[dict]
    debug_attempts: int
    debug_history: List[dict]
    
    # Deployment
    deployed: bool
    workflow_id: Optional[str]
    
    # Modification (post-deploy)
    modification_request: Optional[str]

def create_forgeflow_graph():
    graph = StateGraph(ForgeFlowState)
    
    # Nodes
    graph.add_node("conversation", conversation_node)
    graph.add_node("api_discovery", api_discovery_node)
    graph.add_node("plan_workflow", plan_workflow_node)
    graph.add_node("generate_code", generate_code_node)
    graph.add_node("security_review", security_review_node)
    graph.add_node("sandbox_execute", sandbox_execute_node)
    graph.add_node("self_debug", self_debug_node)
    graph.add_node("present_to_user", present_to_user_node)
    graph.add_node("deploy", deploy_node)
    graph.add_node("modify_workflow", modify_workflow_node)
    
    # Flow
    graph.add_edge(START, "conversation")
    
    graph.add_conditional_edges("conversation", route_after_conversation, {
        "need_clarification": "conversation",     # Loop back for more info
        "requirements_complete": "api_discovery",  # Move to building
        "modification": "modify_workflow",          # Post-deploy modification
    })
    
    graph.add_edge("api_discovery", "plan_workflow")
    graph.add_edge("plan_workflow", "generate_code")
    graph.add_edge("generate_code", "security_review")
    graph.add_edge("security_review", "sandbox_execute")
    
    graph.add_conditional_edges("sandbox_execute", route_after_execution, {
        "success": "present_to_user",
        "failure": "self_debug",
    })
    
    graph.add_conditional_edges("self_debug", route_after_debug, {
        "retry": "sandbox_execute",        # Try again with fix
        "max_attempts": "present_to_user",  # Show user the issue
    })
    
    graph.add_conditional_edges("present_to_user", route_after_present, {
        "approve": "deploy",
        "modify": "modify_workflow",
        "reject": "conversation",
    })
    
    graph.add_edge("modify_workflow", "generate_code")  # Regenerate affected code
    graph.add_edge("deploy", END)
    
    return graph.compile()
```

---

## 9. Project Structure

```
forgeflow/
├── docker-compose.yml              # One command: docker-compose up
├── .env.example                    # Required API keys
├── README.md
│
├── backend/
│   ├── main.py                     # FastAPI app + WebSocket
│   ├── graph.py                    # LangGraph workflow definition
│   │
│   ├── conversation/
│   │   ├── engine.py               # Conversation state machine
│   │   ├── intent_classifier.py    # Classify user intent
│   │   └── requirement_extractor.py # Extract structured requirements
│   │
│   ├── discovery/
│   │   ├── vector_store.py         # ChromaDB setup + search
│   │   ├── api_indexer.py          # Index OpenAPI specs into vectors
│   │   ├── api_selector.py         # LLM-based API selection
│   │   └── specs/                  # Pre-loaded OpenAPI specs
│   │       ├── gmail.json
│   │       ├── slack.json
│   │       ├── jira.json
│   │       ├── sheets.json
│   │       ├── deriv_trading.json
│   │       ├── deriv_account.json
│   │       └── ...
│   │
│   ├── planner/
│   │   ├── dag_builder.py          # DAG generation from requirements + APIs
│   │   ├── data_mapper.py          # Inter-step data flow mapping
│   │   └── models.py               # WorkflowDAG, WorkflowStep schemas
│   │
│   ├── codegen/
│   │   ├── generator.py            # LLM code generation
│   │   ├── security_reviewer.py    # Static analysis + LLM review
│   │   └── templates/              # Code templates for common patterns
│   │       ├── async_http.py
│   │       ├── webhook_listener.py
│   │       ├── websocket_stream.py
│   │       └── error_handling.py
│   │
│   ├── execution/
│   │   ├── sandbox.py              # Docker sandbox runner
│   │   ├── self_debugger.py        # Self-debug loop
│   │   └── test_generator.py       # Auto-generate test cases
│   │
│   ├── modifier/
│   │   ├── nl_modifier.py          # Natural language DAG modifications
│   │   └── code_patcher.py         # Targeted code patching
│   │
│   └── shared/
│       ├── audit.py                # Immutable audit logging
│       ├── config.py               # Configuration
│       └── models.py               # Shared Pydantic models
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx       # Conversation interface
│   │   │   ├── WorkflowCanvas.jsx  # React Flow DAG visualization
│   │   │   ├── CodePanel.jsx       # Syntax-highlighted code view
│   │   │   ├── StatusBar.jsx       # Real-time progress
│   │   │   ├── ApiDiscoveryBadge.jsx # Shows discovered APIs
│   │   │   └── DebugOverlay.jsx    # Self-debug visualization
│   │   └── hooks/
│   │       └── useWebSocket.js     # Real-time updates
│   └── package.json
│
└── tests/
    ├── test_discovery.py           # API discovery accuracy
    ├── test_codegen.py             # Code generation quality
    └── test_self_debug.py          # Self-debug success rate
```

---

## 10. Demo Script (5 Minutes — Meticulously Timed)

### Opening (0:00-0:30) — The Hook
> "Every operations team has the same problem: they know what they need automated, but building the workflow takes a developer weeks. What if you could just... describe it?"
> [Screen shows ForgeFlow's clean UI]

### Act 1: Conversation (0:30-1:30) — Building Intelligence
- Type: *"When the Volatility 75 Index on Deriv moves more than 2% in 5 minutes, alert my trading team on Slack, log it to Google Sheets, and create a review ticket in Jira"*
- Show ForgeFlow asking ONE smart clarifying question
- Show the real-time status: "🔍 Discovering APIs..."
- **API Discovery badges appear:** "Found: Deriv Ticks API ✅", "Found: Slack chat.postMessage ✅", "Found: Google Sheets append ✅", "Found: Jira issue create ✅"

### Act 2: Planning (1:30-2:15) — Visual DAG
- DAG appears node-by-node on the canvas (animated)
- Data flow arrows show how data passes between steps
- Click a node → shows the discovered API details, mapped parameters
- "Notice: steps 2, 3, and 4 run in parallel — ForgeFlow detected they have no dependency on each other"

### Act 3: Code Generation (2:15-3:00) — Real Code
- Code streams into the code panel (syntax highlighted)
- Point out: "Real Python code. Async. Error handling. Retry logic. Not a config file — this actually executes."
- Security review badge: "✅ No hardcoded secrets, ✅ Input validation, ✅ Rate limiting"

### Act 4: Self-Debug (3:00-4:00) — THE WOW MOMENT
- Execute in sandbox
- **Intentionally fails** (wrong Sheets API scope in demo env)
- Red flash on the Google Sheets node
- Self-debugger activates: "🔧 Analyzing failure..."
- Diagnosis appears: "Schema mismatch: Sheets API expects `values` as nested array, got flat list"
- Fix applied: show the diff (2 lines changed)
- Re-execute → **all green** ✅
- "ForgeFlow just fixed its own code. Zero human intervention."

### Act 5: Modification (4:00-4:30) — Living Workflow
- Type: *"Actually, only alert on Slack if the move is more than 3%"*
- DAG updates: conditional node appears between trigger and Slack step
- Code patches in real-time (shows only the diff, not full regen)
- "The workflow is alive. Modify it in English, not code."

### Close (4:30-5:00)
> "From description to discovery to code to debug to deploy — in one conversation. No developer needed. That's ForgeFlow."
> 
> [Show: "Deployed ✅" status]

---

## 11. Answering Every Judge Question (Pre-armed)

From the challenge document's "Questions Worth Considering":

| Question | ForgeFlow's Answer |
|----------|-------------------|
| How do you handle ambiguous requirements? | Confidence threshold: extract what we can, ask max 2 high-impact questions, assume sensible defaults for the rest and tell the user what was assumed |
| What's the right balance between AI autonomy vs. user control? | AI generates, human approves. The visual DAG + code panel give full transparency. One-click deploy only after explicit approval |
| How do you discover APIs when users don't know system names? | Semantic search over API documentation. "Send an email" → finds Gmail API. User never needs to know "messages.send" |
| Can you generate workflows for different platforms? | ForgeFlow generates executable Python — platform agnostic. But the architecture supports output adapters (n8n JSON, Zapier config) as future work |
| How do you handle auth/credentials securely? | Env vars only. Never in code. Security reviewer catches any hardcoded secrets before execution |
| What if a required API doesn't exist? | Tell the user. Suggest alternatives from the knowledge base. Or: "Add your API's OpenAPI spec and ForgeFlow will discover it" |

---

## 12. Build Priority (What to Build First)

Since you said "deepest project wins" — here's the priority order:

### P0 — Must Have (These make or break the demo)
1. API Discovery engine with ChromaDB + real OpenAPI specs (especially Deriv API)
2. LangGraph conversation → planning → code generation pipeline
3. Self-debugging loop (the showstopper)
4. React frontend with chat panel + DAG visualization (React Flow)
5. WebSocket streaming of progress updates

### P1 — Strong Value Add
6. Natural language modification of existing workflows
7. Security review step
8. Parallel execution detection in DAG planner
9. Sandbox execution with Docker

### P2 — Nice to Have (If time permits)
10. Audit logging with reasoning traces
11. Multiple workflow templates
12. Export to other formats (n8n JSON, etc.)

---

## 13. What Beats You — And How to Prevent It

| Threat | Prevention |
|--------|-----------|
| Team builds simple LLM wrapper ("generate code from prompt") | Your API discovery engine + self-debug loop are 2 levels deeper. Show the difference explicitly |
| Team builds on n8n/Zapier and says "we integrated AI" | You generate **executable code**, not platform-locked configs. Point out: "Our workflows run anywhere — Docker, AWS Lambda, bare metal" |
| Demo crashes live | Pre-cache the full demo flow. Have a recorded backup video. Test the demo path 10+ times |
| Judge asks "how is this different from ChatGPT generating code?" | "ChatGPT doesn't discover APIs from documentation, doesn't build visual DAGs, doesn't execute in a sandbox, and doesn't debug its own failures. ForgeFlow does all four autonomously in a pipeline." |
| Judge asks about production readiness | "The generated code includes error handling, retry logic, env-var configuration, and audit logging. It's not a prototype — it's production code generated by a prototype." |

---

## 14. Pre-Hackathon Preparation Checklist

**Before Feb 7:**
- [ ] Download real OpenAPI specs for Gmail, Slack, Jira, Sheets, Deriv API
- [ ] Chunk and test embedding them into ChromaDB
- [ ] Set up Docker Compose with all services
- [ ] Build the React frontend skeleton (chat panel + React Flow canvas)
- [ ] Set up FastAPI backend with WebSocket
- [ ] Test LangGraph basic pipeline
- [ ] Create Deriv demo account and verify API access
- [ ] Prepare the demo script and practice timing
- [ ] Set up fallback: pre-cached LLM responses for demo path

**During the 12 hours:**
- [ ] Hour 1-3: API Discovery engine (ChromaDB + search + LLM selection)
- [ ] Hour 3-5: LangGraph pipeline (conversation → plan → codegen)
- [ ] Hour 5-7: Self-debug loop + sandbox execution
- [ ] Hour 7-9: Frontend polish (DAG animation, code streaming, debug overlay)
- [ ] Hour 9-10: Natural language modification engine
- [ ] Hour 10-11: End-to-end testing with Deriv API demo flow
- [ ] Hour 11-12: Demo rehearsal × 3, bug fixes, polish

---

*"Everyone has the same problem statement, but the deepest project wins." ForgeFlow goes five levels deep where others go one.*
