"""Small auth guard for endpoints that can execute code or commands."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from backend.shared.config import settings


def verify_admin_token(token: str | None, action: str = "perform this action") -> None:
    """Require an explicit admin token unless unsafe demo mode is enabled."""
    if settings.FORGEFLOW_ALLOW_UNAUTH_DANGEROUS:
        return

    expected = settings.FORGEFLOW_ADMIN_TOKEN
    if not expected:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Refusing to {action}: set FORGEFLOW_ADMIN_TOKEN and pass it "
                "as X-ForgeFlow-Admin-Token."
            ),
        )

    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid ForgeFlow admin token")


def require_admin_token(
    x_forgeflow_admin_token: str | None = Header(default=None),
) -> bool:
    verify_admin_token(x_forgeflow_admin_token)
    return True
