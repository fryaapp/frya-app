"""Intent-spezifische Sub-Handler fuer unified_handler.py.

Jeder Handler ist eine reine async-Funktion ohne WebSocket-Abhaengigkeit.
Ausgelagert aus unified_handler.py fuer die 500-Zeilen-Regel.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from app.core.intents import Intent

logger = logging.getLogger(__name__)

_NEIN_KLEINUNTERNEHMER_PATTERNS = [
    re.compile(r'(?:nein|nicht|kein).*kleinunternehmer', re.IGNORECASE),
    re.compile(r'(?:nein|nicht).*§\s*19', re.IGNORECASE),
    re.compile(r'ganz\s+normal\s+mit\s+mwst', re.IGNORECASE),
    re.compile(r'bin\s+kein\s+kleinunternehmer\s+mehr', re.IGNORECASE),
    re.compile(r'nicht\s+mehr\s+kleinunternehmer', re.IGNORECASE),
    re.compile(r'mit\s+(?:umsatz|mwst|mehrwert)steuer', re.IGNORECASE),
]


# ===================================================================
# APPROVE (P-12)
# ===================================================================

async def handle_approve(
    text: str, quick_action: dict | None, tenant_id: str,
) -> tuple[str | None, dict]:
    """APPROVE shortcircuit — P-12: vendor name matching, DB lookup."""
    try:
        from app.agents.service_registry import _InboxService
        inbox_svc = _InboxService()
        approve_case_id = None

        if quick_action and quick_action.get('type') == 'approve':
            approve_case_id = quick_action.get('params', {}).get('case_id')

        if not approve_case_id:
            case_match = re.search(r'CASE-\d{4}-\d{5}', text)
            if case_match:
                case_nr = case_match.group(0)
                import asyncpg
                from app.dependencies import get_settings
                conn = await asyncpg.connect(get_settings().database_url)
                try:
                    row = await conn.fetchrow(
                        "SELECT id FROM case_cases WHERE case_number = $1", case_nr,
                    )
                    if row:
                        approve_case_id = str(row['id'])
                finally:
                    await conn.close()
            else:
                # P-12b: Match vendor name against PENDING approvals
                text_lower = text.lower()
                stop_words = {
                    'gmbh', 'ag', 'ug', 'kg', 'ohg', 'se', 'co', 'mbh',
                    'freigeben', 'buchen', 'genehmigen', 'beleg', 'rechnung',
                    'bitte', 'den', 'die', 'das', 'der', 'und', 'oder', 'von',
                }
                text_words = set(text_lower.split()) - stop_words
                try:
                    import asyncpg as apg_vn
                    from app.dependencies import get_settings as gs_vn
                    conn_vn = await apg_vn.connect(gs_vn().database_url)
                    try:
                        pend_rows = await conn_vn.fetch("""
                            SELECT a.case_id AS approval_case_id,
                                   cc.id AS case_uuid, cc.vendor_name
                            FROM frya_approvals a
                            JOIN case_documents cd
                              ON cd.document_source_id::text = REPLACE(a.case_id, 'doc-', '')
                            JOIN case_cases cc ON cc.id = cd.case_id
                            WHERE a.status = 'PENDING'
                              AND a.action_type = 'booking_finalize'
                              AND cc.vendor_name IS NOT NULL
                        """)
                        best_match = (None, 0)
                        for pr in pend_rows:
                            vn_lower = pr['vendor_name'].lower()
                            if any(w in vn_lower for w in text_words if len(w) >= 4):
                                vn_words = set(vn_lower.split()) - stop_words
                                overlap = len(text_words & vn_words)
                                if overlap > best_match[1]:
                                    best_match = (str(pr['case_uuid']), overlap)
                        if best_match[0] and best_match[1] >= 1:
                            approve_case_id = best_match[0]
                    finally:
                        await conn_vn.close()
                except Exception as vn_exc:
                    logger.warning('Vendor name approval lookup failed: %s', vn_exc)

        if approve_case_id:
            approve_result = await inbox_svc.approve(
                case_id=approve_case_id, tenant_id=tenant_id,
            )
            if approve_result.get('status') == 'approved':
                return 'Freigabe erledigt. Buchung erstellt.', approve_result
            elif approve_result.get('status') == 'no_pending':
                return approve_result.get('message', 'Keine offene Freigabe.'), approve_result
            else:
                return str(approve_result), {}
        else:
            return None, {}
    except Exception as ae:
        logger.warning('APPROVE shortcircuit failed: %s', ae)
        return None, {}


# ===================================================================
# SHOW_CONTACTS (P-08 A2)
# ===================================================================

async def handle_show_contacts(tenant_id: str) -> tuple[str, dict]:
    """P-08 A2: Load all contacts for card_list."""
    try:
        from app.dependencies import get_accounting_repository
        contacts_repo = get_accounting_repository()
        all_contacts = await contacts_repo.list_contacts(uuid.UUID(tenant_id))
        contact_dicts = [
            {
                'name': c.display_name or c.name,
                'contact_type': c.contact_type,
                'email': c.email or '',
                'category': c.category,
            }
            for c in all_contacts if c.is_active
        ]
        return f'{len(contact_dicts)} Kontakte gefunden.', {'contacts': contact_dicts}
    except Exception as ce:
        logger.warning('SHOW_CONTACTS failed: %s', ce)
        return 'Kontakte konnten nicht geladen werden.', {}


# ===================================================================
# CHANGE_KU_STATUS (P-27)
# ===================================================================

async def handle_change_ku_status(
    text: str, user_id: str, tenant_id: str,
) -> str:
    """P-27: Kleinunternehmer-Status via Chat aendern."""
    from app.api.unified_handler import _persist_preference

    ku_nein = any(p.search(text) for p in _NEIN_KLEINUNTERNEHMER_PATTERNS)
    if ku_nein:
        try:
            from app.services.business_profile_service import BusinessProfileService
            await BusinessProfileService().upsert_field(
                user_id, tenant_id, 'is_kleinunternehmer', False,
            )
            await _persist_preference(user_id, tenant_id, 'kleinunternehmer', 'false')
            return (
                'Verstanden. Ab jetzt erstelle ich Rechnungen mit Umsatzsteuer (19%). '
                'Bestehende Rechnungen bleiben unveraendert.'
            )
        except Exception as exc:
            logger.warning('KU-Status change failed: %s', exc)
            return 'KU-Status konnte nicht geaendert werden.'
    else:
        try:
            from app.services.business_profile_service import BusinessProfileService
            await BusinessProfileService().upsert_field(
                user_id, tenant_id, 'is_kleinunternehmer', True,
            )
            await _persist_preference(user_id, tenant_id, 'kleinunternehmer', 'true')
            return (
                'Verstanden. Ab jetzt erstelle ich Rechnungen ohne Umsatzsteuer '
                '(\u00a719 UStG). Bestehende Rechnungen bleiben unveraendert.'
            )
        except Exception as exc:
            logger.warning('KU-Status change failed: %s', exc)
            return 'KU-Status konnte nicht geaendert werden.'


# ===================================================================
# CANCEL_INVOICE (P-27)
# ===================================================================

async def handle_cancel_invoice(
    text: str, tenant_id: str, user_id: str,
) -> tuple[str | None, dict]:
    """P-27: CANCEL_INVOICE — Rechnung stornieren."""
    cancel_match = re.search(r'RE-\d+-\d+', text)
    if not cancel_match:
        return 'Welche Rechnung soll storniert werden? (z.B. RE-2026-054)', {}

    cancel_inv_nr = cancel_match.group(0)
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            row = await conn.fetchrow(
                "SELECT id, invoice_number, status, gross_total, contact_id "
                "FROM frya_invoices WHERE invoice_number = $1 AND tenant_id = $2::uuid",
                cancel_inv_nr, tenant_id,
            )
            if not row:
                return f'Rechnung {cancel_inv_nr} nicht gefunden.', {}

            row = dict(row)
            if row.get('status') in ('CANCELLED', 'VOID', 'REVERSED'):
                return (
                    f'Rechnung {cancel_inv_nr} ist bereits storniert.',
                    {'actions': [], 'content_blocks': []},
                )

            cc_name = ''
            if row.get('contact_id'):
                cc_r = await conn.fetchrow(
                    "SELECT name FROM frya_contacts WHERE id = $1::uuid",
                    str(row['contact_id']),
                )
                if cc_r:
                    cc_name = cc_r['name'] or ''

            from app.services.invoice_pipeline import _eur
            cc_gross = float(row.get('gross_total', 0))
            reply = f'Rechnung {cancel_inv_nr} ({cc_name}, {_eur(cc_gross)}) stornieren?'
            data = {
                'actions': [
                    {
                        'label': 'Ja, stornieren',
                        'chat_text': f'Ja, Rechnung {cancel_inv_nr} stornieren',
                        'style': 'primary',
                        'quick_action': {
                            'type': 'cancel_invoice',
                            'params': {
                                'invoice_id': str(row['id']),
                                'tenant_id': tenant_id,
                                'user_id': user_id,
                            },
                        },
                    },
                    {
                        'label': 'Abbrechen',
                        'chat_text': 'Nein, nicht stornieren',
                        'style': 'text',
                    },
                ],
            }
            return reply, data
        finally:
            await conn.close()
    except Exception as ce:
        logger.warning('CANCEL_INVOICE lookup failed: %s', ce)
        return None, {}


# ===================================================================
# SHOW_CASE (P-25)
# ===================================================================

async def handle_show_case(
    routing_result: dict, quick_action: dict | None,
) -> tuple[str | None, dict]:
    """P-25: SHOW_CASE — Load case detail by case_id."""
    try:
        from app.agents.service_registry import _InboxService
        case_svc = _InboxService()
        sc_case_id = None
        if isinstance(routing_result.get('params'), dict):
            sc_case_id = routing_result['params'].get('case_id')
        if not sc_case_id and quick_action:
            sc_case_id = (quick_action.get('params') or {}).get('case_id')
        if sc_case_id:
            case_data = await case_svc.get_case(case_id=sc_case_id)
            if case_data.get('error'):
                return case_data['error'], {}
            case_info = case_data.get('case', {})
            return (
                f'Hier ist der Beleg von {case_info.get("vendor_name", "unbekannt")}.',
                case_data,
            )
        return None, {}
    except Exception as exc:
        logger.warning('SHOW_CASE shortcircuit failed: %s', exc)
        return None, {}


# ===================================================================
# SHOW_INVOICE
# ===================================================================

async def handle_show_invoice(text: str, tenant_id: str) -> dict | None:
    """SHOW_INVOICE — Load and display specific invoice. Returns full response or None."""
    from app.api.unified_handler import _build_response

    inv_match = re.search(r'RE-\d+-\d+', text)
    if not inv_match:
        return None

    inv_nr = inv_match.group(0)
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            inv_row = await conn.fetchrow(
                "SELECT i.*, c.name as contact_name FROM frya_invoices i "
                "LEFT JOIN frya_contacts c ON c.id = i.contact_id "
                "WHERE i.invoice_number = $1", inv_nr,
            )
        finally:
            await conn.close()

        if not inv_row:
            return _build_response(text=f'Rechnung {inv_nr} nicht gefunden.', routing='regex')

        from app.services.invoice_pipeline import _eur
        inv_status_map = {
            'DRAFT': 'Entwurf', 'SENT': 'Versendet', 'PAID': 'Bezahlt',
            'VOID': 'Storniert', 'CANCELLED': 'Storniert',
            'REVERSED': 'Storniert (Gegenbuchung)', 'OVERDUE': 'Ueberfaellig',
        }
        inv_blocks = [{
            'block_type': 'key_value',
            'data': {'items': [
                {'label': 'Rechnungsnr.', 'value': inv_row['invoice_number']},
                {'label': 'Empfaenger', 'value': inv_row['contact_name'] or ''},
                {'label': 'Status', 'value': inv_status_map.get(inv_row['status'], inv_row['status'])},
                {'label': 'Netto', 'value': _eur(float(inv_row['net_total'] or 0))},
                {'label': 'Brutto', 'value': _eur(float(inv_row['gross_total'] or 0))},
                {'label': 'Datum', 'value': inv_row['invoice_date'].strftime('%d.%m.%Y') if inv_row['invoice_date'] else ''},
                {'label': 'Faellig', 'value': inv_row['due_date'].strftime('%d.%m.%Y') if inv_row['due_date'] else ''},
            ]},
        }]
        inv_pdf_url = f"/api/v1/invoices/{inv_row['id']}/pdf"
        inv_blocks.append({
            'block_type': 'document',
            'data': {'title': f'Rechnung {inv_nr}', 'url': inv_pdf_url, 'format': 'PDF'},
        })
        inv_actions = []
        if inv_row['status'] == 'DRAFT':
            inv_actions = [
                {
                    'label': 'Freigeben & Senden',
                    'chat_text': f'Rechnung {inv_nr} senden',
                    'style': 'primary',
                    'quick_action': {'type': 'send_invoice', 'params': {'invoice_id': str(inv_row['id'])}},
                },
                {
                    'label': 'Verwerfen',
                    'chat_text': f'Rechnung {inv_nr} verwerfen',
                    'style': 'text',
                    'quick_action': {'type': 'void_invoice', 'params': {'invoice_id': str(inv_row['id'])}},
                },
            ]

        return _build_response(
            text=f'Rechnung {inv_nr} — {inv_status_map.get(inv_row["status"], inv_row["status"])}',
            content_blocks=inv_blocks,
            actions=inv_actions,
            context_type='invoice_draft',
            routing='regex',
        )
    except Exception as exc:
        logger.warning('SHOW_INVOICE failed: %s', exc)
        return None


# ===================================================================
# Chart/Data Shortcircuits (P-12b)
# ===================================================================

async def handle_chart_shortcircuit(
    tier_intent: str, tenant_id: str,
) -> tuple[str | None, dict]:
    """P-12b: Shortcircuit ALL chart/data intents — bypass Communicator."""
    try:
        from app.agents.service_registry import build_service_registry
        chart_reg = build_service_registry()
        chart_intent_map = {
            Intent.SHOW_INBOX: ('inbox_service', 'list_pending'),
            Intent.PROCESS_INBOX: ('inbox_service', 'process_first'),
            Intent.SHOW_FINANCIAL_OVERVIEW: ('euer_service', 'get_finance_summary'),
            Intent.SHOW_FINANCE: ('euer_service', 'get_finance_summary'),
            Intent.SHOW_BOOKINGS: ('booking_service', 'list'),
            Intent.SHOW_OPEN_ITEMS: ('open_item_service', 'list'),
            Intent.SHOW_DEADLINES: ('deadline_service', 'list'),
            Intent.SHOW_EXPENSE_CATEGORIES: ('booking_service', 'list'),
            Intent.SHOW_PROFIT_LOSS: ('euer_service', 'get_finance_summary'),
            Intent.SHOW_REVENUE_TREND: ('booking_service', 'list'),
            Intent.SHOW_FORECAST: ('euer_service', 'get_finance_summary'),
        }
        si = chart_intent_map.get(tier_intent)
        if not si:
            return None, {}
        svc_obj = chart_reg.get(si[0])
        if not svc_obj:
            return None, {}
        method = getattr(svc_obj, si[1], None)
        if not method:
            return None, {}

        chart_data = await method(tenant_id=tenant_id) or {}

        texts = {
            Intent.SHOW_INBOX: f'{chart_data.get("count", len(chart_data.get("items", [])))} Belege warten auf deine Freigabe.',
            Intent.PROCESS_INBOX: (
                f'Beleg 1 von {chart_data.get("count", 1)}: Hier sind die Details.'
                if chart_data.get('status') == 'has_items'
                else 'Alles erledigt! Keine Belege warten auf dich.'
            ),
            Intent.SHOW_FINANCE: 'Hier ist deine Finanzuebersicht.',
            Intent.SHOW_FINANCIAL_OVERVIEW: 'Hier ist deine Finanzuebersicht.',
            Intent.SHOW_BOOKINGS: 'Hier sind deine letzten Buchungen.',
            Intent.SHOW_OPEN_ITEMS: 'Hier sind deine offenen Posten.',
            Intent.SHOW_DEADLINES: 'Hier sind deine anstehenden Fristen.',
            Intent.SHOW_EXPENSE_CATEGORIES: 'Hier ist die Aufschluesselung deiner Ausgaben nach Kategorie.',
            Intent.SHOW_PROFIT_LOSS: 'Hier ist deine Gewinn- und Verlustrechnung.',
            Intent.SHOW_REVENUE_TREND: 'Hier ist die Umsatzentwicklung.',
            Intent.SHOW_FORECAST: 'Hier ist die Hochrechnung fuer das Geschaeftsjahr.',
        }
        return texts.get(tier_intent, 'Hier sind die Daten.'), chart_data
    except Exception as exc:
        logger.warning('Chart shortcircuit failed: %s', exc)
        return None, {}


# ===================================================================
# Invoice Draft Review (P-43 Fix B)
# ===================================================================

async def handle_invoice_draft_review(
    text: str, invoice_id: str, pf_data: dict,
    user_id: str, tenant_id: str,
) -> dict:
    """P-43 Fix B: User responds to invoice draft preview."""
    from app.api.unified_handler import _build_response, _save_history, get_session_id, handle_user_message

    inv_mod_patterns = [
        r'(?:aender|änder|change|mach).*(?:betrag|preis|summe|€|euro|\d)',
        r'(?:aender|änder).*(?:adresse|name|empfaenger|empfänger|beschreibung)',
        r'(?:statt|anstatt)\s*\d+',
        r'\d+\s*€?\s*(?:statt|anstatt|draus|daraus)',
        r'(?:betrag|preis|summe)\s*(?:auf|zu|soll|=)\s*\d+',
        r'(?:mach|setze?)\s*\d+\s*€?\s*(?:draus|daraus)',
        r'(?:fuege|füge|add|noch)\s+\d+\s+.+\s+(?:zu|à|a|@)\s*\d+',
        r'(?:andere?|neue?)\s*(?:adresse|beschreibung|position)',
    ]
    is_mod = any(re.search(p, text.lower()) for p in inv_mod_patterns)
    is_send = any(kw in text.lower() for kw in ('freigeben', 'senden', 'verschicken', 'abschicken', 'sieht gut aus'))
    is_void = any(kw in text.lower() for kw in ('verwerfen', 'loeschen', 'löschen', 'stornieren'))

    if is_mod:
        from app.services.invoice_pipeline import handle_modify_invoice
        mod_result = await handle_modify_invoice(
            invoice_id, text, user_id, tenant_id=tenant_id,
        )
        mod_inv_id = mod_result.get('invoice_id', invoice_id)
        _save_history(user_id, text, mod_result.get('text', ''))
        return _build_response(
            text=mod_result.get('text', ''),
            content_blocks=mod_result.get('content_blocks', []),
            actions=mod_result.get('actions', []),
            context_type='invoice_draft',
            routing='pending_flow',
            next_pending_flow={
                'waiting_for': 'invoice_draft_review',
                'invoice_id': mod_inv_id,
                'pending_data': pf_data,
            },
        )

    if is_send:
        from app.services.invoice_pipeline import handle_send_invoice
        send_r = await handle_send_invoice(
            {'invoice_id': invoice_id}, user_id, tenant_id=tenant_id,
        )
        next_pf = None
        if send_r.get('awaiting_email_for_invoice'):
            next_pf = {
                'waiting_for': 'recipient_email',
                'invoice_id': send_r['awaiting_email_for_invoice'],
                'pending_data': pf_data,
            }
        _save_history(user_id, text, send_r.get('text', ''))
        return _build_response(
            text=send_r.get('text', ''),
            content_blocks=send_r.get('content_blocks', []),
            actions=send_r.get('actions', []),
            context_type=send_r.get('context_type', 'none'),
            routing='pending_flow',
            next_pending_flow=next_pf,
        )

    if is_void:
        from app.services.invoice_pipeline import handle_void_invoice
        void_r = await handle_void_invoice({'invoice_id': invoice_id}, user_id)
        _save_history(user_id, text, void_r.get('text', 'Rechnung verworfen.'))
        return _build_response(
            text=void_r.get('text', 'Rechnung verworfen.'),
            content_blocks=void_r.get('content_blocks', []),
            actions=void_r.get('actions', []),
            context_type='none',
            routing='pending_flow',
            next_pending_flow=None,
        )

    # Unknown follow-up — clear pending, route normally
    return await handle_user_message(
        message=text,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=get_session_id(user_id, tenant_id),
        quick_action=None,
        pending_flow=None,
    )


# ===================================================================
# Pending Action (P-43 Fix D)
# ===================================================================

async def handle_pending_action(
    text: str, tenant_id: str, user_id: str, is_confirm: bool,
) -> dict | None:
    """Phase 0b: Check Redis for pending_action, execute or reject.

    Returns response dict or None if no pending action found.
    P3: Every Redis op in try/except, never re-raise.
    P5: Uses _atomic_get_and_delete for cleanup.
    """
    from app.api.unified_handler import _atomic_get_and_delete, _build_response, _get_redis, _save_history

    try:
        rconn = await _get_redis()
        if not rconn:
            return None
        pa_key = f'frya:pending_action:{tenant_id or user_id}'
        # P5: Atomic get+delete
        pa_raw = await _atomic_get_and_delete(rconn, pa_key)
        if not pa_raw:
            return None

        pa_data = json.loads(pa_raw)

        if is_confirm:
            pa_action = pa_data.get('action')
            pa_case_ref = pa_data.get('case_ref')
            pa_params = pa_data.get('params', {})
            pa_confirm_text = pa_data.get('confirm_text', 'Erledigt.')

            if pa_action == 'approve' and pa_case_ref:
                from app.agents.service_registry import _InboxService
                inbox = _InboxService()
                ap_r = await inbox.approve(case_id=pa_case_ref, tenant_id=tenant_id)
                pa_confirm_text = ap_r.get('text', 'Buchung freigegeben.')
            elif pa_action == 'rebooking' and pa_case_ref:
                pa_confirm_text = f'Umbuchung auf {pa_params.get("new_account", "?")} durchgefuehrt.'

            _save_history(user_id, text, pa_confirm_text)
            return _build_response(
                text=pa_confirm_text,
                case_ref=pa_case_ref,
                content_blocks=[{
                    'block_type': 'alert',
                    'data': {'severity': 'success', 'text': pa_confirm_text},
                }],
                routing='pending_action',
            )
        else:
            _save_history(user_id, text, 'Abgebrochen.')
            return _build_response(
                text='Alles klar, abgebrochen. Was kann ich sonst fuer dich tun?',
                routing='pending_action',
            )
    except Exception as exc:
        # P3: Never re-raise Redis errors
        logger.debug('Pending action check failed: %s', exc)
        return None
