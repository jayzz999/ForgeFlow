"""Built-in connector and capability contracts.

The catalog is intentionally declarative: a connector added here is exposed in
status checks, adapter discovery, prompt preflight, and automation spec planning.
Live OAuth/client execution can be layered on per connector without changing the
business-facing planning surface.
"""

CONNECTOR_CATALOG = {
    "schema": {
        "name": "Schema Inspector",
        "aliases": ("schema", "csv", "excel", "sheet", "spreadsheet", "database", "table"),
        "docs_url": "local://forgeflow/schema-inspector",
        "auth_type": "none",
        "env_vars": (),
        "scopes": (),
        "source": "built_in",
        "capabilities": [
            {
                "id": "schema.inspect_file",
                "label": "Inspect Uploaded File",
                "category": "Discovery",
                "risk": "read_only",
                "description": "Read CSV or XLSX headers and sample rows before planning.",
                "methods": ["auth_check", "schema_discovery", "dry_run"],
            },
            {
                "id": "schema.map_fields",
                "label": "Map Source Fields",
                "category": "Discovery",
                "risk": "read_only",
                "description": "Map real source columns into each connector input contract.",
                "methods": ["schema_discovery", "dry_run"],
            },
        ],
    },
    "slack": {
        "name": "Slack",
        "aliases": ("slack", "channel", "workspace"),
        "docs_url": "https://api.slack.com/web",
        "auth_type": "bearer_token",
        "env_vars": ("SLACK_BOT_TOKEN",),
        "scopes": ("chat:write", "channels:read", "users:read.email"),
        "source": "built_in",
        "capabilities": [
            {
                "id": "slack.post_message",
                "label": "Post Slack Message",
                "category": "Messaging",
                "risk": "external_write",
                "description": "Send or draft Slack channel messages with approval gates.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
            {
                "id": "slack.create_channel",
                "label": "Create Slack Channel",
                "category": "Messaging",
                "risk": "external_write",
                "description": "Create a channel after preview and approval.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "gmail": {
        "name": "Gmail",
        "aliases": ("gmail", "email", "mail", "inbox"),
        "docs_url": "https://developers.google.com/gmail/api/reference/rest",
        "auth_type": "oauth2",
        "env_vars": ("GMAIL_ACCESS_TOKEN", "GMAIL_SENDER_EMAIL"),
        "scopes": ("https://www.googleapis.com/auth/gmail.send",),
        "source": "built_in",
        "capabilities": [
            {
                "id": "gmail.send_email",
                "label": "Send Gmail Email",
                "category": "Messaging",
                "risk": "external_write",
                "description": "Draft or send email messages through Gmail.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
            {
                "id": "gmail.create_draft",
                "label": "Create Gmail Draft",
                "category": "Messaging",
                "risk": "external_write",
                "description": "Create a draft without sending it.",
                "methods": ["auth_check", "dry_run", "execute"],
            },
        ],
    },
    "sheets": {
        "name": "Google Sheets",
        "aliases": ("google sheets", "sheets", "spreadsheet", "row", "excel"),
        "docs_url": "https://developers.google.com/sheets/api/reference/rest",
        "auth_type": "oauth2",
        "env_vars": ("GOOGLE_SHEETS_ACCESS_TOKEN", "GOOGLE_SHEET_ID"),
        "scopes": ("https://www.googleapis.com/auth/spreadsheets",),
        "source": "built_in",
        "capabilities": [
            {
                "id": "sheets.append_row",
                "label": "Append Google Sheets Row",
                "category": "Data",
                "risk": "external_write",
                "description": "Append validated rows to an existing spreadsheet.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute"],
            },
            {
                "id": "sheets.read_rows",
                "label": "Read Google Sheets Rows",
                "category": "Data",
                "risk": "read_only",
                "description": "Read rows for schema grounding and lookup steps.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute"],
            },
        ],
    },
    "http": {
        "name": "HTTP/Webhooks",
        "aliases": ("http", "api", "webhook", "rest api", "endpoint", "url"),
        "docs_url": "https://developer.mozilla.org/en-US/docs/Web/HTTP",
        "auth_type": "custom",
        "env_vars": (),
        "scopes": (),
        "source": "built_in",
        "capabilities": [
            {
                "id": "http.request",
                "label": "Call HTTP API",
                "category": "API",
                "risk": "network_call",
                "description": "Call generic REST APIs from a validated request schema.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute"],
            },
        ],
    },
    "approval": {
        "name": "Human Approval",
        "aliases": ("approval", "approve", "review"),
        "docs_url": "local://forgeflow/approval",
        "auth_type": "none",
        "env_vars": (),
        "scopes": (),
        "source": "built_in",
        "capabilities": [
            {
                "id": "approval.wait",
                "label": "Human Approval Gate",
                "category": "Safety",
                "risk": "approval_required",
                "description": "Pause before sending, posting, writing, deleting, or changing access.",
                "methods": ["dry_run", "execute"],
            },
        ],
    },
    "hubspot": {
        "name": "HubSpot",
        "aliases": ("hubspot", "hubspot crm"),
        "docs_url": "https://developers.hubspot.com/docs/api/overview",
        "auth_type": "bearer_token",
        "env_vars": ("HUBSPOT_ACCESS_TOKEN",),
        "scopes": ("crm.objects.contacts.write", "crm.objects.deals.write"),
        "source": "catalog",
        "capabilities": [
            {
                "id": "hubspot.create_contact",
                "label": "Create HubSpot Contact",
                "category": "CRM",
                "risk": "external_write",
                "description": "Create or preview a CRM contact from grounded source fields.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "hubspot.update_deal",
                "label": "Update HubSpot Deal",
                "category": "CRM",
                "risk": "external_write",
                "description": "Update deal properties after approval.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "salesforce": {
        "name": "Salesforce",
        "aliases": ("salesforce", "sales cloud"),
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
        "auth_type": "oauth2",
        "env_vars": ("SALESFORCE_ACCESS_TOKEN", "SALESFORCE_INSTANCE_URL"),
        "scopes": ("api", "refresh_token"),
        "source": "catalog",
        "capabilities": [
            {
                "id": "salesforce.create_record",
                "label": "Create Salesforce Record",
                "category": "CRM",
                "risk": "external_write",
                "description": "Create a Salesforce object from a validated schema mapping.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "salesforce.update_record",
                "label": "Update Salesforce Record",
                "category": "CRM",
                "risk": "external_write",
                "description": "Update an existing Salesforce object with approval controls.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "stripe": {
        "name": "Stripe",
        "aliases": ("stripe", "payment", "invoice", "refund", "subscription"),
        "docs_url": "https://docs.stripe.com/api",
        "auth_type": "bearer_token",
        "env_vars": ("STRIPE_API_KEY",),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "stripe.retrieve_payment",
                "label": "Retrieve Stripe Payment",
                "category": "Finance",
                "risk": "read_only",
                "description": "Fetch payment details before deciding on follow-up actions.",
                "methods": ["auth_check", "dry_run", "execute"],
            },
            {
                "id": "stripe.create_refund",
                "label": "Create Stripe Refund",
                "category": "Finance",
                "risk": "external_write",
                "description": "Create a refund only after approval and idempotency checks.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "jira": {
        "name": "Jira",
        "aliases": ("jira", "atlassian issue", "jira issue", "jira ticket"),
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        "auth_type": "api_token",
        "env_vars": ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "jira.create_issue",
                "label": "Create Jira Issue",
                "category": "Work Management",
                "risk": "external_write",
                "description": "Create a Jira issue from an approved workflow event.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "jira.transition_issue",
                "label": "Transition Jira Issue",
                "category": "Work Management",
                "risk": "external_write",
                "description": "Move an issue through a validated transition.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "notion": {
        "name": "Notion",
        "aliases": ("notion", "wiki", "page", "database"),
        "docs_url": "https://developers.notion.com/reference/intro",
        "auth_type": "bearer_token",
        "env_vars": ("NOTION_TOKEN",),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "notion.create_page",
                "label": "Create Notion Page",
                "category": "Knowledge",
                "risk": "external_write",
                "description": "Create a Notion page from approved generated content.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "notion.update_database",
                "label": "Update Notion Database",
                "category": "Knowledge",
                "risk": "external_write",
                "description": "Insert or update a Notion database row using real property schema.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "airtable": {
        "name": "Airtable",
        "aliases": ("airtable", "base", "record"),
        "docs_url": "https://airtable.com/developers/web/api/introduction",
        "auth_type": "bearer_token",
        "env_vars": ("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID"),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "airtable.create_record",
                "label": "Create Airtable Record",
                "category": "Data",
                "risk": "external_write",
                "description": "Create records from mapped source fields.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "airtable.update_record",
                "label": "Update Airtable Record",
                "category": "Data",
                "risk": "external_write",
                "description": "Update records using approved field mappings.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "teams": {
        "name": "Microsoft Teams",
        "aliases": ("microsoft teams", "teams"),
        "docs_url": "https://learn.microsoft.com/en-us/graph/api/resources/teams-api-overview",
        "auth_type": "oauth2",
        "env_vars": ("MICROSOFT_GRAPH_TOKEN",),
        "scopes": ("ChannelMessage.Send",),
        "source": "catalog",
        "capabilities": [
            {
                "id": "teams.post_message",
                "label": "Post Teams Message",
                "category": "Messaging",
                "risk": "external_write",
                "description": "Post a Teams message after preview and approval.",
                "methods": ["auth_check", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "calendar": {
        "name": "Google Calendar",
        "aliases": ("google calendar", "calendar", "schedule", "training"),
        "docs_url": "https://developers.google.com/calendar/api/v3/reference",
        "auth_type": "oauth2",
        "env_vars": ("GOOGLE_CALENDAR_ACCESS_TOKEN",),
        "scopes": ("https://www.googleapis.com/auth/calendar.events",),
        "source": "catalog",
        "capabilities": [
            {
                "id": "calendar.create_event",
                "label": "Create Calendar Event",
                "category": "Scheduling",
                "risk": "external_write",
                "description": "Schedule calendar events from grounded attendee and time data.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "okta": {
        "name": "Okta",
        "aliases": ("okta", "provision", "access", "account", "group"),
        "docs_url": "https://developer.okta.com/docs/reference/",
        "auth_type": "api_token",
        "env_vars": ("OKTA_ORG_URL", "OKTA_API_TOKEN"),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "okta.assign_group",
                "label": "Assign Okta Group",
                "category": "Identity",
                "risk": "external_write",
                "description": "Assign a user to an access group after approval.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
            {
                "id": "okta.create_user",
                "label": "Create Okta User",
                "category": "Identity",
                "risk": "external_write",
                "description": "Create an identity account from validated HR source data.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
    "zendesk": {
        "name": "Zendesk",
        "aliases": ("zendesk", "support ticket", "support"),
        "docs_url": "https://developer.zendesk.com/api-reference/",
        "auth_type": "api_token",
        "env_vars": ("ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN"),
        "scopes": (),
        "source": "catalog",
        "capabilities": [
            {
                "id": "zendesk.create_ticket",
                "label": "Create Zendesk Ticket",
                "category": "Support",
                "risk": "external_write",
                "description": "Create a support ticket from approved workflow context.",
                "methods": ["auth_check", "schema_discovery", "dry_run", "execute", "compensate"],
            },
        ],
    },
}


def capability_specs() -> list[tuple[str, str, str, str, list[str]]]:
    specs = []
    for service, info in CONNECTOR_CATALOG.items():
        for capability in info["capabilities"]:
            specs.append((
                capability["id"],
                service,
                capability["label"],
                capability["risk"],
                list(capability.get("methods", ("dry_run", "execute"))),
            ))
    return specs


BASE_CAPABILITIES = [
    {
        "id": capability["id"],
        "label": capability["label"],
        "category": capability["category"],
        "risk": capability["risk"],
        "requires_auth": list(info.get("env_vars", ())),
        "description": capability["description"],
        "dry_run": "dry_run" in capability.get("methods", ()),
        "source": service,
    }
    for service, info in CONNECTOR_CATALOG.items()
    for capability in info["capabilities"]
]

SERVICE_TO_DEFAULT_CAPABILITY = {
    service: info["capabilities"][0]["id"]
    for service, info in CONNECTOR_CATALOG.items()
    if info["capabilities"]
}
SERVICE_TO_DEFAULT_CAPABILITY.update({
    "schema": "schema.inspect_file",
    "slack": "slack.post_message",
    "gmail": "gmail.send_email",
    "sheets": "sheets.append_row",
    "http": "http.request",
    "approval": "approval.wait",
    "stripe": "stripe.create_refund",
    "calendar": "calendar.create_event",
    "okta": "okta.assign_group",
})

SERVICE_MARKERS = {
    service: tuple(info.get("aliases", (service,)))
    for service, info in CONNECTOR_CATALOG.items()
}
