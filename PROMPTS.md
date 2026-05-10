# ForgeFlow Development Prompts

Use these prompts when developing, debugging, or demoing ForgeFlow. They are written for an AI coding assistant working in this repository.

## Project Orientation

```text
Analyze this ForgeFlow project end to end. Explain the current backend, frontend, connector, workflow generation, sandbox, review/approval, and live execution architecture. Identify the files I should understand first and any risks before changing code.
```

```text
Map the user journey from a plain-English prompt in Builder to generated workflow files, sandbox execution, Review actions, approval, and live connector execution. Include exact backend endpoints and frontend components involved.
```

## Demo Prompts

```text
Run and visually test the local ForgeFlow demo. Use the Builder prompt: "Automate HR onboarding from an uploaded Excel sheet, send a welcome email, post a Slack announcement, and append tracking data." Verify Review shows editable Gmail, Slack, and Sheets actions. Do not approve live actions unless I explicitly ask.
```

```text
Prepare ForgeFlow for an interview demo. Check that Slack, Gmail, and Google Sheets connectors are live, Docker sandbox works, Review actions are editable, and approval sends/posts/appends only after explicit approval. Report any blockers in plain English.
```

```text
Run the latest generated workflow through Review visually. Confirm the Review panel is populated, scrollable, editable, and that the action labels match the real live behavior. Do not click Approve & run live.
```

## Product Behavior

```text
Make ForgeFlow truthful about what happened during a workflow run. If code only dry-ran, say no external writes happened. If Review approved live actions, show per-action connector results and exact failure reasons.
```

```text
Improve the Review experience so non-technical users can edit Gmail recipients, subjects, bodies, Slack channels/messages, and Google Sheets rows before approval. Ensure the backend executes the edited values.
```

```text
When a generated workflow does not emit structured dry-run JSON, build Review actions from the generated DAG instead. Keep the actions editable and safe, with placeholder employee values the user can change before approval.
```

## Backend Work

```text
Inspect backend/main.py and backend/graph.py for the workflow generation, sandbox, connector preflight, live-review, and approve-live paths. Add focused tests for any behavior change.
```

```text
Add or update backend tests that verify:
- live-review parses structured dry-run outputs
- live-review falls back to DAG actions when stdout is unstructured
- approve-live executes edited review actions
- Slack provider ok:false is treated as failure
- Gmail send_email uses the Gmail messages/send endpoint
```

```text
Debug why a workflow deployed but Review is empty. Find the latest workflow ID, inspect artifacts/execution_result.json and artifacts/dag.json, then update the review parser or DAG fallback so the user gets reviewable actions.
```

## Frontend Work

```text
Improve the Builder Review UI. Make the panel scrollable inside the Builder layout, keep Approve & run live reachable, and make editable action cards fit on desktop and mobile without overlapping.
```

```text
Update frontend/src/App.jsx so Review cards are editable, validation errors are visible, and approval is disabled when edited Sheets JSON is invalid. Verify with a browser screenshot.
```

```text
Visually test the Builder page at http://127.0.0.1:3002/?view=builder after changes. Check the header, discovered API badges, Review panel, editable fields, scroll behavior, result cards, and code/canvas split.
```

## Connector Setup

```text
Verify the live connector setup for Slack, Gmail, and Google Sheets. Run safe read-only probes first. For Gmail, also verify send permission only with an explicit test draft/send instruction from me.
```

```text
Explain how to connect Gmail and Google Sheets through Google OAuth for a non-technical user. Include OAuth consent screen, scopes, web application client, redirect URI, tester access, and reauthorization after scope changes.
```

```text
Debug Gmail ACCESS_TOKEN_SCOPE_INSUFFICIENT. Check configured OAuth scopes, confirm the current token can read profile, explain why old tokens do not gain new scopes automatically, and provide the reauthorization steps.
```

```text
Debug why Sheets appears unchanged after approval. Read the configured spreadsheet and range through the Sheets connector, report the exact spreadsheet title, tab, range, and latest rows.
```

## Safety And Approval

```text
Review all paths that can write to external systems. Confirm they require explicit approval, do not run during sandbox dry-run, and display per-action results after execution.
```

```text
Before approving any live action, summarize exactly what will be sent, posted, or appended. Ask for explicit approval if the user has not already requested the live run.
```

```text
Check that provider failures are not counted as successes. Slack HTTP 200 with ok:false should fail; Google 401 should refresh token once; Google 403 should show the provider error.
```

## Evals And Quality

```text
Improve the Evals section so it evaluates the last real run: expected connectors, generated actions, approval requirement, live result success/failure, and whether the output matched the prompt.
```

```text
Create focused eval cases for HR onboarding prompts with variations:
- uploaded Excel sheet
- broad "automate HR department onboarding"
- explicit Slack channel
- explicit employee data
- missing credentials
```

## Documentation

```text
Update README.md and docs/SPEC_SHEET.md to match the current implementation. Ensure docs say Gmail sends after approval, Review cards are editable, and Google OAuth is required for Gmail/Sheets.
```

```text
Write a short interviewer-facing explanation of ForgeFlow: problem, approach, architecture, demo flow, safety model, connector setup, and limitations.
```

```text
Create a release checklist for the demo. Include server startup, Docker, OAuth, Slack channel membership, Google Sheet ID, Builder prompt, Review edits, live approval, and verification steps.
```

## Refactoring

```text
Refactor the live review parser into small testable functions without changing behavior. Preserve support for structured dry-run outputs, alternate generated field names, and DAG fallback.
```

```text
Reduce sidebar complexity by merging low-level runtime tools into fewer user-facing sections. Keep Builder, Runtime, Connectors, Run History, Ingestions, Evals, Templates, Dashboard, and App Builder aligned with current product value.
```

## Verification Commands

```text
Run the focused verification suite:
python -m py_compile backend/main.py
pytest backend/tests/test_pipeline_smoke.py backend/tests/test_security_boundaries.py -q
cd frontend && npm run build
Then restart the backend and visually verify the local app.
```

```text
After changing Review or connector behavior, verify:
- GET /api/workflows/{workflow_id}/live-review returns actions
- POST /api/workflows/{workflow_id}/approve-live accepts edited actions
- Builder Review shows editable fields
- no live write happens unless Approve & run live is clicked
```
