# ForgeFlow Spec Sheet

## Product Summary

ForgeFlow is a plain-English automation builder. A user describes a workflow, ForgeFlow generates and tests a runnable workflow package, then presents editable live actions for human review before touching external systems.

## Demo Use Case

Prompt:

```text
Automate HR onboarding from an uploaded Excel sheet, send a welcome email, post a Slack announcement, and append tracking data.
```

Expected result after approval:

- Gmail sends welcome emails.
- Slack posts onboarding announcements to the configured channel.
- Google Sheets receives appended tracking rows.
- The run result shows per-action success or failure.

## Core User Flow

1. User enters a natural-language automation request.
2. ForgeFlow extracts intent, discovers matching connectors, and builds a workflow DAG.
3. ForgeFlow generates a Python workflow project and validates it.
4. Docker sandbox executes the workflow when available.
5. ForgeFlow creates a review list from structured dry-run output or from the generated DAG fallback.
6. User edits Gmail, Slack, and Sheets action cards.
7. User approves the live run.
8. ForgeFlow executes live connector calls and records the result.

## Current Live Connectors

| Connector | Current Behavior | Auth |
|-----------|------------------|------|
| Gmail | Sends emails after review approval; can also create drafts when a workflow explicitly uses draft action | Google OAuth |
| Slack | Posts messages to the configured Slack channel after review approval | Slack bot token |
| Google Sheets | Appends rows to the configured spreadsheet after review approval | Google OAuth |

## Review Actions

Gmail review card:

- To
- Subject
- Body

Slack review card:

- Channel
- Message

Google Sheets review card:

- Range
- Rows JSON

Approval sends exactly the edited values shown in Review.

## Safety Rules

- No external write happens during code generation or sandbox dry run.
- External writes require the **Approve & run live** button.
- Review cards are editable before approval.
- Provider failures are shown per action.
- If a generated workflow logs text instead of returning structured dry-run JSON, ForgeFlow falls back to the workflow DAG and still builds reviewable actions.

## Demo Setup Checklist

- Backend running on `http://127.0.0.1:8000`.
- Frontend running on `http://127.0.0.1:3002` or `http://localhost:3000`.
- Docker running for sandbox execution.
- Slack bot token configured and bot invited to the target channel.
- Google OAuth configured with Gmail and Sheets scopes.
- Gmail OAuth reauthorized after adding send/compose scopes.
- `GOOGLE_SHEET_ID` points to the sheet used in the demo.

## Google OAuth Scopes

Required Gmail/Sheets scopes for the demo:

```text
https://www.googleapis.com/auth/gmail.send
https://www.googleapis.com/auth/gmail.compose
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/spreadsheets
```

If Gmail sends fail with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`, remove old ForgeFlow access from the Google account and run Start OAuth again.

## Known Demo Notes

- The broad prompt `automate hr department for onboarding` may use placeholder employee values. Edit these in Review before approval.
- Slack and Sheets actions may duplicate if the same workflow is approved multiple times.
- Gmail sends real email when approved; use safe test recipients during demos.

## Success Criteria

A demo is successful when:

- Builder produces a deployed workflow.
- Review shows editable Gmail, Slack, and Sheets actions.
- Approval completes with all actions succeeded.
- The recipient receives email, Slack receives the message, and the configured Google Sheet has new rows.
