"""Kein LLM, nur direkte Service-Calls fuer Button-Klicks."""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class ActionRouter:
    # Invoice pipeline actions handled by invoice_pipeline module
    _PIPELINE_ACTIONS = frozenset({'send_invoice', 'void_invoice', 'edit_invoice'})
    _TEMPLATE_ACTIONS = frozenset({'set_template'})

    def __init__(self, services: dict[str, Any] | None = None):
        self.services = services or {}

    async def execute(self, quick_action: dict) -> Optional[dict]:
        action_type = quick_action.get("type")
        params = quick_action.get("params", {})

        # Invoice pipeline actions: delegate to invoice_pipeline module
        if action_type in self._PIPELINE_ACTIONS:
            return await self._handle_invoice_action(action_type, params)

        # Template actions
        if action_type in self._TEMPLATE_ACTIONS:
            return await self._handle_template_action(action_type, params)

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

    async def _handle_invoice_action(self, action_type: str, params: dict) -> dict:
        """Delegate to invoice_pipeline handlers."""
        try:
            from app.services.invoice_pipeline import (
                handle_send_invoice, handle_void_invoice,
            )
            user_id = params.pop('user_id', 'system')

            if action_type == 'send_invoice':
                result = await handle_send_invoice(params, user_id)
            elif action_type == 'void_invoice':
                result = await handle_void_invoice(params, user_id)
            elif action_type == 'edit_invoice':
                # Edit returns to form — just return invoice_id
                return {
                    'intent': 'EDIT_INVOICE',
                    'routing': 'action_router',
                    'result': {
                        'invoice_id': params.get('invoice_id'),
                        'action': 'edit',
                    },
                }
            else:
                return {'intent': 'ERROR', 'routing': 'action_router', 'error': 'Unknown action'}

            return {
                'intent': action_type.upper(),
                'routing': 'action_router',
                'result': result,
            }
        except Exception as e:
            logger.error("Invoice pipeline %s: %s", action_type, e)
            return {
                'intent': 'ERROR',
                'routing': 'action_router',
                'error': str(e),
            }

    async def _handle_template_action(self, action_type: str, params: dict) -> dict:
        """Handle template selection via ActionRouter."""
        try:
            template = params.get('template', 'clean')
            user_id = params.pop('user_id', 'system')
            tenant_id = params.pop('tenant_id', 'default')

            from app.pdf.template_registry import TEMPLATES
            if template not in TEMPLATES:
                return {
                    'intent': 'ERROR',
                    'routing': 'action_router',
                    'error': f'Unbekanntes Template: {template}',
                }

            # Save preference
            from app.api.chat_ws import _persist_preference
            await _persist_preference(user_id, tenant_id, 'invoice_template', template)

            title = TEMPLATES[template]['title']
            return {
                'intent': 'SET_TEMPLATE',
                'routing': 'action_router',
                'result': {
                    'text': f'Rechnungs-Template auf "{title}" geaendert.',
                    'content_blocks': [{
                        'block_type': 'alert',
                        'data': {'severity': 'success', 'text': f'Template "{title}" gespeichert.'},
                    }],
                    'actions': [
                        {'label': 'Rechnung erstellen', 'chat_text': 'Rechnung erstellen', 'style': 'primary'},
                        {'label': 'Vorschau', 'chat_text': 'Rechnungs-Vorschau zeigen', 'style': 'secondary'},
                    ],
                },
            }
        except Exception as e:
            logger.error('Template action %s: %s', action_type, e)
            return {'intent': 'ERROR', 'routing': 'action_router', 'error': str(e)}

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
