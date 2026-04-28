"""ForgeFlow Integrations — Production-quality service clients.

Pre-built, tested clients for all supported services.
These are used by generated workflows to ensure REAL integrations, not placeholders.

Supported services:
- Slack: Messages, channels, user lookup, reactions, file uploads
- Gmail: Send/read emails, labels
- Google Sheets: Read/write/append rows, create spreadsheets
- HTTP: Generic REST client for any API
"""

from backend.integrations.slack_client import SlackClient
from backend.integrations.gmail_client import GmailClient
from backend.integrations.sheets_client import GoogleSheetsClient
from backend.integrations.http_client import HTTPClient

# Registry of all available integrations
INTEGRATIONS = {
    "slack": {
        "client": SlackClient,
        "name": "Slack",
        "description": "Team messaging, channels, notifications",
        "auth_type": "bearer_token",
        "env_vars": ["SLACK_BOT_TOKEN"],
        "capabilities": [
            "send_message", "create_channel", "invite_to_channel",
            "list_channels", "list_users", "add_reaction", "upload_file",
            "lookup_user_by_email",
        ],
    },
    "gmail": {
        "client": GmailClient,
        "name": "Gmail",
        "description": "Email sending, reading, labels",
        "auth_type": "oauth2",
        "env_vars": ["GMAIL_ACCESS_TOKEN", "GMAIL_SENDER_EMAIL"],
        "capabilities": [
            "send_email", "list_messages", "get_message", "list_labels",
        ],
    },
    "sheets": {
        "client": GoogleSheetsClient,
        "name": "Google Sheets",
        "description": "Spreadsheet operations, data logging, tracking",
        "auth_type": "oauth2",
        "env_vars": ["GOOGLE_SHEETS_ACCESS_TOKEN"],
        "capabilities": [
            "append_row", "read_range", "update_range", "create_spreadsheet",
        ],
    },
    "http": {
        "client": HTTPClient,
        "name": "HTTP/REST",
        "description": "Generic HTTP client for any REST API",
        "auth_type": "custom",
        "env_vars": [],
        "capabilities": [
            "get", "post", "put", "patch", "delete", "health_check",
        ],
    },
}


def get_client(service: str, **kwargs):
    """Get a client instance for a service.

    Args:
        service: Service name (slack, gmail, sheets, http)
        **kwargs: Passed to the client constructor

    Returns:
        Client instance

    Raises:
        ValueError: If service is not supported
    """
    service = service.lower().strip()
    if service not in INTEGRATIONS:
        # Try fuzzy match
        for key in INTEGRATIONS:
            if key in service or service in INTEGRATIONS[key]["name"].lower():
                service = key
                break
        else:
            raise ValueError(
                f"Unknown service: {service}. "
                f"Supported: {', '.join(INTEGRATIONS.keys())}"
            )
    return INTEGRATIONS[service]["client"](**kwargs)


def list_integrations() -> list[dict]:
    """List all available integrations with their capabilities."""
    return [
        {
            "service": key,
            "name": info["name"],
            "description": info["description"],
            "capabilities": info["capabilities"],
            "env_vars": info["env_vars"],
        }
        for key, info in INTEGRATIONS.items()
    ]
