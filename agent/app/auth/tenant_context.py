"""Zentraler Tenant-Kontext: Einzige Quelle fuer die aktuelle tenant_id.

NIEMALS tenant_id aus Request-Body, Query-Params oder User-Input nehmen.
Immer aus dem authentifizierten JWT Token oder der Session.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.auth.models import AuthUser


def get_current_tenant_id(user: AuthUser) -> str:
    """Holt die Tenant-ID aus dem authentifizierten User.

    Wirft 403 wenn kein Tenant zugeordnet.
    NIEMALS aus Request-Body, Query-Params oder User-Input.
    """
    if not user.tenant_id:
        raise HTTPException(403, "Kein Tenant zugeordnet")
    return str(user.tenant_id)


def require_tenant_id(user: AuthUser) -> str:
    """Alias fuer get_current_tenant_id - expliziter Name fuer Dependency Injection."""
    return get_current_tenant_id(user)
