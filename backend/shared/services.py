"""Single source of truth for ForgeFlow-supported integrations."""

SUPPORTED_SERVICES = {
    "slack": {
        "name": "Slack",
        "aliases": ("slack",),
        "docs_url": "https://api.slack.com/web",
        "env_vars": ("SLACK_BOT_TOKEN",),
    },
    "gmail": {
        "name": "Gmail",
        "aliases": ("gmail", "smtp", "email"),
        "docs_url": "https://support.google.com/mail/answer/185833",
        "env_vars": ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
    },
    "sheets": {
        "name": "Google Sheets",
        "aliases": ("google sheets", "sheets", "spreadsheet"),
        "docs_url": "https://developers.google.com/sheets/api/reference/rest",
        "env_vars": ("GOOGLE_API_KEY", "GOOGLE_SHEET_ID"),
    },
    "http": {
        "name": "HTTP/Webhooks",
        "aliases": ("http", "webhook", "rest api", "url"),
        "docs_url": "https://developer.mozilla.org/en-US/docs/Web/HTTP",
        "env_vars": (),
    },
}

SUPPORTED_SERVICE_NAMES = tuple(info["name"] for info in SUPPORTED_SERVICES.values())
SUPPORTED_SERVICE_LABEL = ", ".join(SUPPORTED_SERVICE_NAMES)


def is_supported_service(value: str) -> bool:
    """Return whether a free-form service label maps to a supported service."""
    normalized = (value or "").lower().strip()
    if not normalized:
        return False
    for key, info in SUPPORTED_SERVICES.items():
        if normalized == key or normalized == info["name"].lower():
            return True
        if any(alias in normalized for alias in info["aliases"]):
            return True
    return False


def docs_url_for_service(value: str) -> str:
    """Best-effort docs URL for a supported service label."""
    normalized = (value or "").lower().strip()
    for key, info in SUPPORTED_SERVICES.items():
        if normalized == key or normalized == info["name"].lower():
            return info["docs_url"]
        if any(alias in normalized for alias in info["aliases"]):
            return info["docs_url"]
    return SUPPORTED_SERVICES["http"]["docs_url"]
