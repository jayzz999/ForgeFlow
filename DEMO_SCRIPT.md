# ForgeFlow Demo Script (5 Minutes)

## Pre-Demo Checklist
- [ ] Backend running on port 8000 (`python -m uvicorn backend.main:app --port 8000`)
- [ ] Frontend running on port 3000 (`cd frontend && npm run dev`)
- [ ] Browser open to http://localhost:3000
- [ ] Terminal visible for backup
- [ ] Demo mode tested once before going live

---

## The Script

### 0:00 - 0:30 | THE HOOK

> "Every trading team spends weeks wiring APIs together. Connect Deriv to Slack. Pipe data to Sheets. Create Jira tickets for anomalies. That's weeks of boilerplate just to get basic automation.
>
> What if you could just **describe what you want** and an AI builds the entire workflow — discovers the right APIs, writes the code, tests it, fixes its own bugs, and deploys it?"

**[Point to ForgeFlow on screen]**

> "That's ForgeFlow."

---

### 0:30 - 1:00 | THE REQUEST

**[Click "Load Demo Workflow" button OR type:]**

> "When the Volatility 75 Index moves more than 2% in 5 minutes, alert my trading team on Slack, log the event to Google Sheets, and create a Jira ticket for investigation."

**[Press Enter / Click Forge]**

> "Watch what happens. No drag-and-drop. No templates. Just natural language."

---

### 1:00 - 1:45 | API DISCOVERY

**[As API badges appear one by one:]**

> "ForgeFlow is semantically searching through 28 API endpoints across 6 services. It's not matching keywords — it's using vector embeddings to find the *right* APIs for each action.
>
> Look — it found Deriv's tick subscription endpoint, Slack's postMessage, Google Sheets append, and Jira issue creation. Four services, discovered automatically."

---

### 1:45 - 2:30 | DAG + CODE GENERATION

**[As DAG nodes appear with bounce animation:]**

> "Now it's building an execution graph. Each node appears as the plan forms. Notice steps 3, 4, and 5 are in parallel — they all depend on step 2 but can run simultaneously.
>
> And now the code is streaming in — real, executable Python with proper error handling, authentication, and data flow between services."

**[Point to code panel with typewriter effect]**

---

### 2:30 - 3:30 | THE WOW MOMENT (Self-Debug)

**[When nodes flash red:]**

> "It failed! The WebSocket connection to Deriv timed out. But watch what happens next..."

**[Pause for dramatic effect as debug kicks in]**

> "ForgeFlow is **diagnosing the root cause** — it identified this as a NETWORK_ERROR and is adding connection retry logic with exponential backoff."

**[When nodes turn orange then green:]**

> "Fix applied. Retrying. And... all green. It **healed itself**. No human intervention. This is the self-debugging loop — it can do this up to 3 times, categorizing errors and generating targeted patches."

> "This is what separates ForgeFlow from every other automation tool."

---

### 3:30 - 4:15 | NATURAL LANGUAGE MODIFICATION

**[After confetti celebration, type in chat:]**
> "Change the price threshold to 3% and add a cooldown of 10 minutes between alerts"

> "The workflow is already deployed, but I can modify it with natural language. No re-building. No re-deploying. It understands what I want to change and patches the running code."

---

### 4:15 - 4:45 | THE DIFFERENTIATOR

> "Let me be clear about what just happened:
>
> - **Zapier** lets you connect pre-built blocks
> - **n8n** lets you code custom nodes
> - **ForgeFlow** generates the *entire workflow from scratch* — from API discovery to executable code to self-healing deployment
>
> That's 5 layers of AI depth. Not a wrapper around an LLM. A full autonomous engineering pipeline."

---

### 4:45 - 5:00 | CLOSE

> "ForgeFlow. Describe it. Forge it. Deploy it."

> "Built with LangGraph, Gemini, ChromaDB, FastAPI, and React. Thank you."

---

## Recovery Playbook

| Situation | Recovery |
|-----------|----------|
| Gemini API is slow (>5s) | "Let me switch to demo mode for reliable timing" — click Demo button |
| WebSocket drops | Auto-reconnects in 1-2 seconds (built-in) |
| Browser crashes | Open new tab, go to localhost:3000 |
| Code gen produces bad code | Self-debug loop handles it — this IS the feature |
| Judges ask to try it | Let them type their own workflow prompt |

## Key Talking Points for Q&A

- **"How is this different from just calling ChatGPT?"** — ForgeFlow has a structured pipeline with vector search, DAG planning, security review, sandbox execution, and self-debugging. ChatGPT just generates text.
- **"Does it actually execute the code?"** — Yes, in a subprocess sandbox with 15-second timeout and stdout/stderr capture.
- **"How does self-debugging work?"** — LLM receives the error + code + context, categorizes the error type, identifies root cause, and generates a targeted fix. Not random retry — intelligent diagnosis.
- **"What about security?"** — Every generated workflow goes through a security review node that checks for unsafe patterns (subprocess calls, file system access, hardcoded credentials).
