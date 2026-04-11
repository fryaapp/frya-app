"""Automatische tenant_id via ContextVar.

Setzt tenant_id bei jedem HTTP-Request automatisch.
Services koennen tenant_id ueber get_current_tenant() holen
OHNE dass jeder Caller es explizit uebergeben muss.

Der bestehende tenant_id-Parameter in Services bleibt als Fallback.
Wenn ein Service explizit tenant_id bekommt, hat das Prioritaet.
Wenn nicht, wird get_current_tenant() verwendet.
Wenn beides None: ValueError (kein stiller Fallback, kein Default-Tenant).
"""

from contextvars import ContextVar
import logging

logger = logging.getLogger(__name__)

_current_tenant: ContextVar[str | None] = ContextVar('current_tenant', default=None)


def set_current_tenant(tenant_id: str) -> None:
    """Setzt die tenant_id fuer den aktuellen Request-Kontext."""
    _current_tenant.set(tenant_id)


def get_current_tenant() -> str | None:
    """Gibt die tenant_id des aktuellen Request-Kontexts zurueck.
    None wenn keine gesetzt (z.B. ausserhalb eines Requests)."""
    return _current_tenant.get()


def require_current_tenant() -> str:
    """Wie get_current_tenant(), aber wirft ValueError wenn None.
    Fuer Stellen wo tenant_id PFLICHT ist."""
    tid = _current_tenant.get()
    if tid is None:
        raise ValueError(
            "Kein tenant_id verfuegbar — weder Parameter noch ContextVar. "
            "Wurde die tenant_middleware registriert?"
        )
    return tid


def resolve_tenant(explicit: str | None = None) -> str:
    """Einheitlicher Resolver: Explizit > ContextVar > ValueError.
    Das ist der Pattern den JEDER Service nutzen soll.

    Args:
        explicit: Explizit uebergebener tenant_id (hat Prioritaet)

    Returns:
        tenant_id als String

    Raises:
        ValueError wenn weder explicit noch ContextVar gesetzt
    """
    tid = explicit or get_current_tenant()
    if not tid:
        raise ValueError(
            "Kein tenant_id: weder Parameter noch ContextVar. "
            "Caller muss tenant_id uebergeben oder Middleware registriert sein."
        )
    return tid
