"""Kein LLM, nur direkte Service-Calls fuer Button-Klicks."""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class ActionRouter:
    def __init__(self, services: dict[str, Any] | None = None):
        self.services = services or {}

    async def execute(self, quick_action: dict) -> Optional[dict]:
        action_type = quick_action.get("type")
        params = quick_action.get("params", {})
        handler = self.HANDLERS.get(action_type)
        if not handler:
            return None  # Unknown -> full pipeline

        service_name, method_name = handler
        service = self.services.get(service_name)
        if not service:
            logger.error("Service not found: %s", service_name)
            return None
        method = getattr(service, method_name, None)
        if not method:
            logger.error("Method not found: %s.%s", service_name, method_name)
            return None

        try:
            result = await method(**params)
            return {
                "intent": action_type.upper(),
                "routing": "action_router",
                "result": result,
            }
        except Exception as e:
            logger.error("ActionRouter %s: %s", action_type, e)
            return {
                "intent": "ERROR",
                "routing": "action_router",
                "error": str(e),
            }

    HANDLERS = {
        "approve": ("inbox_service", "approve"),
        "reject": ("inbox_service", "reject"),
        "defer": ("inbox_service", "defer"),
        "show_inbox": ("inbox_service", "list_pending"),
        "show_deadlines": ("deadline_service", "list"),
        "show_finance": ("euer_service", "get_finance_summary"),
        "show_contact": ("contact_service", "get_dossier"),
        "show_bookings": ("booking_service", "list"),
        "show_open_items": ("open_item_service", "list"),
        "create_invoice": ("invoice_service", "prepare_form"),
        "finalize_invoice": ("invoice_service", "finalize"),
        "export_datev": ("euer_service", "export_datev"),
        "show_settings": ("settings_service", "get"),
        "update_setting": ("settings_service", "update"),
    }
