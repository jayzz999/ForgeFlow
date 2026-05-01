"""Single source of truth for ForgeFlow-supported integrations."""

from backend.connectors.catalog import CONNECTOR_CATALOG

SUPPORTED_SERVICES = {
    service: {
        "name": info["name"],
        "aliases": info.get("aliases", (service,)),
        "docs_url": info.get("docs_url", ""),
        "env_vars": info.get("env_vars", ()),
        "auth_type": info.get("auth_type", "api_key"),
        "scopes": info.get("scopes", ()),
        "source": info.get("source", "catalog"),
    }
    for service, info in CONNECTOR_CATALOG.items()
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
