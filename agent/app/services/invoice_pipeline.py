"""Ausgangsrechnungs-Pipeline: Draft + Vorschau, Send, Void, Paperless-Archivierung.

Implements the full outgoing invoice flow per FRYA-CC-RECHNUNGS-PIPELINE.md:
  1. handle_create_invoice() — DRAFT + PDF + content_blocks preview
  2. handle_send_invoice()   — Finalize + Mail + Paperless + Hash-Chain
  3. handle_void_invoice()   — GoBD-compliant VOID (no delete)
  4. archive_outgoing_invoice() — Paperless upload with metadata
"""
from __future__ import annotations

import base64
import logging
import uuid
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _eur(amount: float) -> str:
    """Format as German EUR string."""
    return f'{amount:,.2f} \u20ac'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ---------------------------------------------------------------------------
# §14 UStG Pflichtangaben: Compliance-Gate (frya_business_profile)
# ---------------------------------------------------------------------------

async def validate_company_data(user_id: str, tenant_id: str) -> tuple[bool, list[str]]:
    """Check if all required §14 UStG company data is present.

    Delegates to compliance_gate.check_compliance('create_invoice').
    Returns: (all_valid, list_of_missing_questions)
    """
    try:
        from app.services.compliance_gate import check_compliance
        allowed, missing_questions, _profile = await check_compliance(
            user_id, tenant_id, 'create_invoice',
        )
        return allowed, missing_questions
    except Exception as exc:
        logger.warning('validate_company_data (compliance_gate) failed: %s', exc)
        return True, []  # Don't block on errors


async def _resolve_tenant() -> uuid.UUID:
    from app.case_engine.tenant_resolver import resolve_tenant_id
    tid = await resolve_tenant_id()
    if not tid:
        raise RuntimeError('tenant_unavailable')
    return uuid.UUID(tid)


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


# ---------------------------------------------------------------------------
# Schritt 2: Invoice-Draft erstellen + Vorschau
# ---------------------------------------------------------------------------

async def handle_create_invoice(invoice_data: dict, user_id: str) -> dict:
    """Create Invoice DRAFT + PDF + return content_blocks preview.

    Args:
        invoice_data: Structured data from communicator INVOICE_DATA extraction.
            Required: contact_name, items[{description, quantity, unit_price, tax_rate}]
            Optional: contact_email, contact_address, payment_terms_days, notes
        user_id: Current user ID for audit.

    Returns:
        dict with text, content_blocks, actions for WebSocket response.
    """
    from app.accounting.invoice_service import InvoiceService

    tid = await _resolve_tenant()

    # §14 UStG: Compliance-Gate pruefen bevor Rechnung erstellt wird
    try:
        from app.services.compliance_gate import check_compliance, count_missing_fields
        allowed, missing_questions, profile = await check_compliance(
            user_id, str(tid), 'create_invoice',
        )
    except Exception as exc:
        logger.warning('Compliance check failed: %s', exc)
        allowed, missing_questions, profile = True, [], None

    if not allowed:
        first_question = missing_questions[0]
        # Count total missing for progress hint
        try:
            total_missing = await count_missing_fields(user_id, str(tid), 'create_invoice')
        except Exception:
            total_missing = 1
        remaining = total_missing - 1
        if remaining > 0:
            hint = f'\n(Noch {remaining} kurze Frage{"n" if remaining > 1 else ""} danach.)'
        else:
            hint = ''
        intro = 'Gerne! Fuer deine erste Rechnung brauche ich ein paar Angaben ueber dein Unternehmen. Das machen wir einmal und dann nie wieder.\n\n' if not profile else ''
        # Buttons for Kleinunternehmer question
        actions: list[dict] = []
        if 'Kleinunternehmer' in first_question:
            actions = [
                {'label': 'Nein, ganz normal mit MwSt', 'chat_text': 'Nein, ganz normal mit MwSt', 'style': 'primary'},
                {'label': 'Ja, Kleinunternehmer §19', 'chat_text': 'Ja, Kleinunternehmer nach §19 UStG', 'style': 'secondary'},
            ]
        return {
            'text': f'{intro}{first_question}{hint}',
            'content_blocks': [],
            'actions': actions,
            'context_type': 'none',
            '_pending_intent': 'CREATE_INVOICE',
            '_pending_data': invoice_data,
        }

    # --- Empfaenger-Adresse Compliance-Gate ---
    # §14 Abs.4 UStG: Vollstaendige Anschrift des Leistungsempfaengers erforderlich
    contact_address = invoice_data.get('contact_address') or {}
    contact_name = invoice_data.get('contact_name', '')

    # Parse contact_address: can be dict or string
    if isinstance(contact_address, str) and contact_address.strip():
        # Try to parse "Strasse, PLZ Ort" or "Strasse, PLZ Ort"
        import re as _re
        _addr_street = ''
        _addr_zip = ''
        _addr_city = ''
        parts = [p.strip() for p in contact_address.split(',')]
        if len(parts) >= 2:
            _addr_street = parts[0]
            rest = parts[1].strip()
            m = _re.match(r'(\d{4,5})\s+(.*)', rest)
            if m:
                _addr_zip = m.group(1)
                _addr_city = m.group(2)
            else:
                _addr_city = rest
        elif len(parts) == 1:
            m = _re.match(r'(.+?)\s+(\d{4,5})\s+(.*)', parts[0])
            if m:
                _addr_street = m.group(1).rstrip(',')
                _addr_zip = m.group(2)
                _addr_city = m.group(3)
            else:
                _addr_street = parts[0]
    elif isinstance(contact_address, dict):
        _addr_street = contact_address.get('street', '') or invoice_data.get('contact_street', '')
        _addr_zip = contact_address.get('zip', '') or invoice_data.get('contact_zip', '')
        _addr_city = contact_address.get('city', '') or invoice_data.get('contact_city', '')
    else:
        _addr_street = invoice_data.get('contact_street', '')
        _addr_zip = invoice_data.get('contact_zip', '')
        _addr_city = invoice_data.get('contact_city', '')

    # --- HARTER COMPLIANCE-GATE (P-05): Reine Code-Validierung ---
    # Merged data: Absender (profile) + Empfaenger + Dokument
    from app.services.compliance_gate import validate as _gate_validate
    from app.services.invoice_type import determine_invoice_type

    # Rechnungstyp bestimmen (Kleinunternehmer, etc.)
    try:
        _pre_inv_type = determine_invoice_type(profile or {}, invoice_data)
    except Exception:
        _pre_inv_type = {'type': 'STANDARD_B2B', 'tax_rate': 19, 'show_tax_line': True}

    _gate_data: dict[str, Any] = {}
    # Absender aus Profil
    if profile:
        _gate_data.update({
            'company_name': profile.get('company_name', ''),
            'company_street': profile.get('company_street', ''),
            'company_zip': profile.get('company_zip', ''),
            'company_city': profile.get('company_city', ''),
            'tax_number': profile.get('tax_number', ''),
            'ust_id': profile.get('ust_id', ''),
        })
    # Empfaenger
    _gate_data['contact_name'] = contact_name
    _gate_data['contact_street'] = _addr_street
    _gate_data['contact_zip'] = _addr_zip
    _gate_data['contact_city'] = _addr_city
    # Dokument
    _gate_data['line_items'] = invoice_data.get('items', [])
    _gate_data['tax_rate'] = _pre_inv_type.get('tax_rate', 19)
    # Typ-spezifisch
    if _pre_inv_type.get('type') == 'KLEINUNTERNEHMER':
        _gate_data['is_kleinunternehmer'] = True
        _gate_data['tax_note'] = _pre_inv_type.get('tax_note', '')

    _gate_result = _gate_validate('invoice', _gate_data)

    if not _gate_result.passed:
        # Kategorisierte Fehlermeldung
        if _gate_result.missing_sender:
            # Absender-Daten fehlen -> Onboarding-Flow (Legacy)
            return {
                'text': f'Fuer die Rechnung fehlen noch Angaben zu deinem Unternehmen: {", ".join(_gate_result.missing_sender)}',
                'content_blocks': [],
                'actions': [],
                'context_type': 'none',
                '_pending_intent': 'CREATE_INVOICE',
                '_pending_data': invoice_data,
            }
        if _gate_result.missing_recipient:
            return {
                'text': (
                    f'Fuer die Rechnung an {contact_name} brauche ich noch: '
                    f'{", ".join(_gate_result.missing_recipient)}. '
                    f'Das ist gesetzlich vorgeschrieben (§14 UStG).'
                ),
                'content_blocks': [],
                'actions': [],
                'context_type': 'none',
                '_pending_intent': 'CREATE_INVOICE',
                '_pending_data': invoice_data,
            }
        if _gate_result.missing_document:
            return {
                'text': f'Fuer die Rechnung fehlt noch: {", ".join(_gate_result.missing_document)}',
                'content_blocks': [],
                'actions': [],
                'context_type': 'none',
                '_pending_intent': 'CREATE_INVOICE',
                '_pending_data': invoice_data,
            }

    repo = _get_repo()
    svc = InvoiceService(repo)

    # 1. Kontakt finden oder erstellen
    # contact_name already set above from recipient validation
    if not contact_name:
        contact_name = invoice_data.get('contact_name', 'Unbekannt')
    contact = await repo.find_or_create_contact(
        tid, contact_name, contact_type='CUSTOMER',
    )

    # Update contact address if provided
    if _addr_street or _addr_zip or _addr_city:
        try:
            import asyncpg
            from app.dependencies import get_settings
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                await conn.execute(
                    "UPDATE frya_contacts SET address_street = COALESCE(NULLIF($2, ''), address_street), "
                    "address_zip = COALESCE(NULLIF($3, ''), address_zip), "
                    "address_city = COALESCE(NULLIF($4, ''), address_city) "
                    "WHERE id = $1::uuid",
                    contact.id, _addr_street, _addr_zip, _addr_city,
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('Contact address update failed: %s', exc)

    # Update contact email if provided
    contact_email = invoice_data.get('contact_email')
    if contact_email:
        try:
            from app.dependencies import get_settings
            import asyncpg
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                await conn.execute(
                    "UPDATE frya_contacts SET email = $2 WHERE id = $1::uuid",
                    contact.id, contact_email,
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('Contact email update failed: %s', exc)

    # 2. Invoice erstellen (DRAFT)
    due_days = int(invoice_data.get('payment_terms_days', 14))
    due_date = date.today() + timedelta(days=due_days)

    invoice = await svc.create_invoice(
        tenant_id=tid,
        contact_id=contact.id,
        items=invoice_data.get('items', []),
        due_date=due_date,
        header_text=None,
        footer_text=invoice_data.get('notes'),
    )

    # 3. Rechnungstyp — FESTER Wert aus _pre_inv_type (schon vor Gate bestimmt)
    inv_type_info = _pre_inv_type

    # 4. Berechne Vorschau-Werte mit FESTEM Steuersatz (P-05: keine Division!)
    items = invoice_data.get('items', [])
    total_net = sum(i.get('quantity', 1) * i.get('unit_price', 0) for i in items)
    # FESTER Steuersatz aus invoice_type.py — NICHT aus Items oder Berechnung
    tax_rate = int(inv_type_info.get('tax_rate', 19))
    total_tax = total_net * tax_rate / 100
    total_gross = total_net + total_tax

    # 5. PDF-URL
    pdf_url = f'/api/v1/invoices/{invoice.id}/pdf'

    # 6. Vorschau-Response bauen
    invoice_id_str = str(invoice.id)

    # Build address string for preview
    _preview_addr_parts = [_addr_street]
    if _addr_zip or _addr_city:
        _preview_addr_parts.append(f'{_addr_zip} {_addr_city}'.strip())
    _preview_addr = ', '.join(p for p in _preview_addr_parts if p)

    # Build preview items — must match PDF content exactly
    preview_items = [
        {'label': 'Empfaenger', 'value': contact_name},
    ]
    if _preview_addr:
        preview_items.append({'label': 'Adresse', 'value': _preview_addr})
    preview_items.append({'label': 'Rechnungsnr.', 'value': invoice.invoice_number})

    # Line items detail
    for item in items:
        qty = item.get('quantity', 1)
        qty_str = str(int(qty)) if qty == int(qty) else str(qty)
        desc = item.get('description', '')
        up = item.get('unit_price', 0)
        preview_items.append({
            'label': desc,
            'value': f'{qty_str} x {_eur(up)}',
        })

    preview_items.append({'label': 'Netto', 'value': _eur(total_net)})
    if inv_type_info.get('show_tax_line', True):
        preview_items.append({'label': f'MwSt ({tax_rate}%)', 'value': _eur(total_tax)})
    preview_items.append({'label': 'Brutto', 'value': _eur(total_gross)})
    preview_items.append({'label': 'Zahlungsziel', 'value': due_date.strftime('%d.%m.%Y')})
    # Invoice type hint
    _type_labels = {
        'KLEINUNTERNEHMER': 'Kleinunternehmer §19',
        'KLEINBETRAG': 'Kleinbetragsrechnung §33',
        'INNERGEMEINSCHAFTLICH': 'Innergemeinschaftlich (0% MwSt)',
        'REVERSE_CHARGE': 'Reverse Charge §13b',
        'STANDARD_B2B': 'Standard B2B',
        'STANDARD_B2C': 'Standard B2C',
    }
    inv_type_label = _type_labels.get(inv_type_info.get('type', ''), '')
    if inv_type_label:
        preview_items.append({'label': 'Rechnungstyp', 'value': inv_type_label})

    # Tax note (e.g. Kleinunternehmer §19 hint) — show in BOTH text and preview
    tax_note = inv_type_info.get('tax_note')
    if tax_note:
        preview_items.append({'label': 'Hinweis', 'value': tax_note})
    text_suffix = f'\n\n_Hinweis: {tax_note}_' if tax_note else ''

    return {
        'text': f'Rechnung {invoice.invoice_number} fuer {contact_name} erstellt (Entwurf).{text_suffix}',
        'content_blocks': [
            {
                'block_type': 'key_value',
                'data': {'items': preview_items},
            },
            {
                'block_type': 'document',
                'data': {
                    'title': f'Rechnung {invoice.invoice_number}',
                    'url': pdf_url,
                    'format': 'PDF',
                    'size': '~40 KB',
                },
            },
        ],
        'actions': [
            {
                'label': 'Freigeben & Senden',
                'chat_text': f'Rechnung {invoice.invoice_number} senden',
                'style': 'primary',
                'quick_action': {
                    'type': 'send_invoice',
                    'params': {
                        'invoice_id': invoice_id_str,
                        'recipient_email': contact_email,
                    },
                },
            },
            {
                'label': 'Bearbeiten',
                'chat_text': f'Rechnung {invoice.invoice_number} bearbeiten',
                'style': 'secondary',
                'quick_action': {
                    'type': 'edit_invoice',
                    'params': {'invoice_id': invoice_id_str},
                },
            },
            {
                'label': 'Verwerfen',
                'chat_text': 'Rechnung verwerfen',
                'style': 'text',
                'quick_action': {
                    'type': 'void_invoice',
                    'params': {'invoice_id': invoice_id_str},
                },
            },
        ],
        'context_type': 'invoice_draft',
    }


# ---------------------------------------------------------------------------
# Schritt 3: Send-Action (nach Freigabe)
# ---------------------------------------------------------------------------

async def handle_send_invoice(params: dict, user_id: str) -> dict:
    """User clicked 'Freigeben & Senden'.

    1. Check email (ask if missing)
    2. Generate PDF + ZUGFeRD
    3. Finalize (DRAFT -> SENT, Hash-Chain, OP)
    4. Mail via Brevo
    5. Archive in Paperless
    6. Return success response
    """
    invoice_id = params.get('invoice_id')
    recipient_email = params.get('recipient_email')

    if not invoice_id:
        return {
            'text': 'Fehler: Keine Rechnungs-ID angegeben.',
            'content_blocks': [],
            'actions': [],
        }

    tid = await _resolve_tenant()

    # Compliance-Gate: send_invoice_email requires company_email
    try:
        from app.services.compliance_gate import check_compliance
        allowed, missing_q, _profile = await check_compliance(
            user_id, str(tid), 'send_invoice_email',
        )
        if not allowed and missing_q:
            return {
                'text': missing_q[0],
                'content_blocks': [],
                'actions': [],
                '_pending_intent': 'SEND_INVOICE',
                '_pending_data': params,
            }
    except Exception as exc:
        logger.warning('Send compliance check failed: %s', exc)
    repo = _get_repo()

    # Load invoice
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM frya_invoices WHERE id = $1::uuid",
                invoice_id,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error('Failed to load invoice %s: %s', invoice_id, exc)
        return {
            'text': 'Rechnung konnte nicht geladen werden.',
            'content_blocks': [],
            'actions': [],
        }

    if not row:
        return {
            'text': 'Rechnung nicht gefunden.',
            'content_blocks': [],
            'actions': [],
        }

    # Convert asyncpg.Record to dict — .get() works but getattr() does NOT
    row = dict(row)

    invoice_number = row.get('invoice_number', '?')
    contact_id = row.get('contact_id')
    gross_total = row.get('gross_total', 0)
    net_total = row.get('net_total', 0)
    tax_total = row.get('tax_total', 0)
    invoice_date = row.get('invoice_date')
    due_date_val = row.get('due_date')

    # Check email — try contact if not provided
    contact_name = ''
    if contact_id:
        try:
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                contact_row = await conn.fetchrow(
                    "SELECT email, name FROM frya_contacts WHERE id = $1::uuid",
                    str(contact_id),
                )
                if contact_row:
                    if not recipient_email:
                        recipient_email = contact_row.get('email')
                    contact_name = contact_row.get('name', '')
            finally:
                await conn.close()
        except Exception:
            pass

    if not recipient_email:
        return {
            'text': 'An welche E-Mail-Adresse soll die Rechnung gehen?',
            'content_blocks': [],
            'actions': [],
            'awaiting_email_for_invoice': invoice_id,
        }

    # 1. Generate PDF + ZUGFeRD
    _tid_str = str(tid)
    try:
        pdf_bytes = await _generate_invoice_pdf(
            tid, invoice_id, row, recipient_email, tenant_id_str=_tid_str,
        )
    except Exception as exc:
        logger.error('PDF generation failed: %s', exc)
        return {
            'text': f'PDF-Erstellung fehlgeschlagen: {exc}',
            'content_blocks': [],
            'actions': [],
        }

    # 2. Load company name from DB (not from settings fallback)
    try:
        from app.pdf.template_registry import get_company_data_for_template
        _company_data = await get_company_data_for_template(user_id, _tid_str)
        company = _company_data.get('company_name', 'Meine Firma')
    except Exception:
        company = 'Meine Firma'

    # 3. Send via Brevo
    try:
        from app.dependencies import get_mail_service, get_settings
        mail_service = get_mail_service()
        settings = get_settings()

        pdf_b64 = base64.b64encode(pdf_bytes).decode('ascii')
        filename = f'Rechnung_{invoice_number}.pdf'

        due_str = due_date_val.strftime('%d.%m.%Y') if due_date_val else '14 Tage'
        gross_str = _eur(float(gross_total))

        await mail_service.send_mail(
            to=recipient_email,
            subject=f'Rechnung {invoice_number} \u2014 {company}',
            body_html=(
                f'<p>Sehr geehrte Damen und Herren,</p>'
                f'<p>anbei erhalten Sie Rechnung <strong>{invoice_number}</strong> '
                f'\u00fcber <strong>{gross_str}</strong>.</p>'
                f'<p>Zahlungsziel: {due_str}</p>'
                f'<p>Mit freundlichen Gr\u00fc\u00dfen<br/>{company}</p>'
            ),
            body_text=(
                f'Rechnung {invoice_number} \u00fcber {gross_str}.\n'
                f'Zahlungsziel: {due_str}\nPDF im Anhang.\n\n{company}'
            ),
            tenant_id=_tid_str,
            attachments=[{'name': filename, 'content': pdf_b64}],
        )
    except Exception as exc:
        logger.error('Mail sending failed: %s', exc)
        return {
            'text': f'Rechnung erstellt, aber Versand fehlgeschlagen: {exc}',
            'content_blocks': [],
            'actions': [],
        }

    # 3. Finalize (DRAFT -> SENT)
    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(
                "UPDATE frya_invoices SET status = 'SENT' WHERE id = $1::uuid AND status = 'DRAFT'",
                invoice_id,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning('Invoice status update failed: %s', exc)

    # 4. Archive in Paperless (non-fatal)
    try:
        await archive_outgoing_invoice(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            contact_name=row.get('contact_name', ''),
            gross_total=gross_total,
            pdf_bytes=pdf_bytes,
            tenant_id=str(tid),
        )
    except Exception as exc:
        logger.warning('Paperless archival failed (non-fatal): %s', exc)

    logger.info('Invoice %s sent to %s', invoice_number, recipient_email)

    return {
        'text': f'Rechnung {invoice_number} versendet an {recipient_email} ({_eur(float(gross_total))}).',
        'content_blocks': [
            {
                'block_type': 'alert',
                'data': {
                    'severity': 'success',
                    'text': f'Rechnung versendet. Zahlungsziel: {due_str}.',
                },
            },
        ],
        'actions': [
            {
                'label': 'Noch eine Rechnung',
                'chat_text': 'Weitere Rechnung erstellen',
                'style': 'secondary',
            },
            {
                'label': 'Offene Posten',
                'chat_text': 'Wer schuldet mir Geld?',
                'style': 'text',
            },
        ],
        'context_type': 'none',
    }


# ---------------------------------------------------------------------------
# Schritt 4: Paperless-Archivierung
# ---------------------------------------------------------------------------

async def archive_outgoing_invoice(
    invoice_id: str,
    invoice_number: str,
    contact_name: str,
    gross_total: Any,
    pdf_bytes: bytes,
    tenant_id: str,
) -> None:
    """Archive outgoing invoice in Paperless (GoBD-Pflicht)."""
    try:
        from app.dependencies import get_settings
        settings = get_settings()
        paperless_url = getattr(settings, 'paperless_url', '') or ''
        paperless_token = getattr(settings, 'paperless_api_token', '') or ''
        if not paperless_url:
            logger.info('Paperless not configured, skipping archival')
            return

        from app.connectors.dms_paperless import PaperlessConnector
        connector = PaperlessConnector(paperless_url, paperless_token)

        # Upload PDF
        filename = f'{invoice_number}.pdf'
        title = f'{invoice_number} \u2014 {contact_name}'
        result = await connector.upload_document(pdf_bytes, filename, title)
        task_id = result.get('task_id') if isinstance(result, dict) else str(result)
        logger.info('Paperless upload: task_id=%s for %s', task_id, invoice_number)

        # Wait briefly for processing, then set metadata
        if task_id:
            import asyncio
            await asyncio.sleep(3)
            task_status = await connector.get_task_status(task_id)
            doc_id = task_status.get('related_document')

            if doc_id:
                # Set document type
                doc_type_id = await connector.find_or_create_document_type('Ausgangsrechnung')
                # Set correspondent (= Empfaenger/Kunde)
                corr_id = await connector.find_or_create_correspondent(contact_name)
                # Set tag
                tag_id = await connector.find_or_create_tag('frya:gebucht', '#4CAF50')

                metadata: dict[str, Any] = {}
                if doc_type_id:
                    metadata['document_type'] = doc_type_id
                if corr_id:
                    metadata['correspondent'] = corr_id
                if tag_id:
                    metadata['tags'] = [tag_id]

                if metadata:
                    await connector.update_document_metadata(doc_id, metadata)

                # Custom fields
                cf_ids = await connector.get_custom_field_ids()
                custom_fields = []
                if 'betrag_brutto' in cf_ids:
                    custom_fields.append({
                        'field': cf_ids['betrag_brutto'],
                        'value': str(gross_total),
                    })
                if 'rechnungsnummer' in cf_ids:
                    custom_fields.append({
                        'field': cf_ids['rechnungsnummer'],
                        'value': invoice_number,
                    })
                if 'frya_status' in cf_ids:
                    custom_fields.append({
                        'field': cf_ids['frya_status'],
                        'value': 'SENT',
                    })
                if custom_fields:
                    await connector.update_document_metadata(doc_id, {
                        'custom_fields': custom_fields,
                    })

                logger.info('Paperless metadata set for doc_id=%s (%s)', doc_id, invoice_number)
            else:
                logger.warning('Paperless task %s has no related_document yet', task_id)

    except Exception as exc:
        logger.warning('Paperless archival error: %s', exc)
        raise


# ---------------------------------------------------------------------------
# Schritt 5: Void-Action
# ---------------------------------------------------------------------------

async def handle_void_invoice(params: dict, user_id: str) -> dict:
    """User clicked 'Verwerfen'. Set status=VOID (GoBD: no delete)."""
    invoice_id = params.get('invoice_id')
    if not invoice_id:
        return {
            'text': 'Fehler: Keine Rechnungs-ID.',
            'content_blocks': [],
            'actions': [],
        }

    try:
        import asyncpg
        from app.dependencies import get_settings
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            result = await conn.execute(
                "UPDATE frya_invoices SET status = 'VOID' WHERE id = $1::uuid AND status = 'DRAFT'",
                invoice_id,
            )
        finally:
            await conn.close()
        logger.info('Invoice %s voided by %s', invoice_id, user_id)
    except Exception as exc:
        logger.error('Invoice void failed: %s', exc)
        return {
            'text': f'Rechnung konnte nicht verworfen werden: {exc}',
            'content_blocks': [],
            'actions': [],
        }

    return {
        'text': 'Rechnung verworfen.',
        'content_blocks': [],
        'actions': [
            {
                'label': 'Neue Rechnung',
                'chat_text': 'Rechnung erstellen',
                'style': 'secondary',
            },
            {
                'label': 'Zurueck zur Inbox',
                'chat_text': 'Was liegt in der Inbox?',
                'style': 'text',
            },
        ],
        'context_type': 'none',
    }


# ---------------------------------------------------------------------------
# Helper: PDF generation (shared by send pipeline)
# ---------------------------------------------------------------------------

async def _generate_invoice_pdf(
    tid: uuid.UUID,
    invoice_id: str,
    row: Any,
    recipient_email: str | None = None,
    tenant_id_str: str | None = None,
) -> bytes:
    """Generate PDF + ZUGFeRD for an invoice row.

    Uses the user's selected template (clean/professional/minimal).
    Falls back to the legacy template if new templates fail.
    """
    from app.dependencies import get_settings
    settings = get_settings()

    # Ensure row is a dict (asyncpg.Record doesn't support getattr for columns)
    if not isinstance(row, dict):
        row = dict(row)

    invoice_number = row.get('invoice_number', '?')
    net_total = row.get('net_total', 0)
    tax_total = row.get('tax_total', 0)
    gross_total = row.get('gross_total', 0)
    invoice_date = row.get('invoice_date')
    due_date_val = row.get('due_date')
    contact_id = row.get('contact_id')

    # Load contact
    contact_dict = {'name': '', 'street': '', 'zip': '', 'city': ''}
    if contact_id:
        try:
            import asyncpg
            conn = await asyncpg.connect(settings.database_url)
            try:
                c_row = await conn.fetchrow(
                    "SELECT name, address_street, address_zip, address_city FROM frya_contacts WHERE id = $1::uuid",
                    str(contact_id),
                )
                if c_row:
                    contact_dict = {
                        'name': c_row['name'] or '',
                        'street': c_row['address_street'] or '' if c_row['address_street'] else '',
                        'zip': c_row['address_zip'] or '' if c_row['address_zip'] else '',
                        'city': c_row['address_city'] or '' if c_row['address_city'] else '',
                    }
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('Contact load for PDF failed: %s', exc)

    # Load invoice line items from DB
    db_items_list: list[dict] = []
    try:
        import asyncpg as _apg2
        _conn2 = await _apg2.connect(settings.database_url)
        try:
            _item_rows = await _conn2.fetch(
                "SELECT description, quantity, unit_price, tax_rate, "
                "net_amount, tax_amount, gross_amount, unit "
                "FROM frya_invoice_items WHERE invoice_id = $1::uuid ORDER BY position",
                invoice_id,
            )
            for _ir in _item_rows:
                db_items_list.append({
                    'description': _ir['description'] or '',
                    'quantity': float(_ir['quantity'] or 1),
                    'unit': _ir['unit'] or 'Stk',
                    'unit_price': float(_ir['unit_price'] or 0),
                    'tax_rate': float(_ir['tax_rate'] or 19),
                    'total_price': float(_ir['gross_amount'] or 0),
                })
        finally:
            await _conn2.close()
    except Exception as exc:
        logger.warning('Invoice items load failed: %s', exc)

    # Load company data from user preferences (template-aware)
    _tid_str = tenant_id_str or str(tid)
    try:
        from app.pdf.template_registry import (
            get_company_data_for_template, get_company_logo_b64,
            render_invoice_pdf, get_template_name,
        )
        tenant_dict = await get_company_data_for_template('', _tid_str)
        logo_b64 = await get_company_logo_b64('', _tid_str)

        # Load user's selected template + kleinunternehmer
        # Use IN ($1, 'default', '') for fallback across tenant_ids
        import asyncpg as _apg
        _conn = await _apg.connect(settings.database_url)
        try:
            _tpl_rows = await _conn.fetch(
                "SELECT key, value FROM frya_user_preferences "
                "WHERE tenant_id IN ($1, 'default', '') "
                "AND key IN ('invoice_template', 'kleinunternehmer', "
                "'default_skonto_percent', 'default_skonto_days') "
                "ORDER BY CASE WHEN tenant_id = $1 THEN 0 ELSE 1 END",
                _tid_str,
            )
            # Prefer specific tenant_id over default
            _tpl_prefs: dict[str, str] = {}
            for r in reversed(_tpl_rows):
                _tpl_prefs[r['key']] = r['value']
        finally:
            await _conn.close()

        template_key = get_template_name(_tpl_prefs.get('invoice_template'))
        kleinunternehmer = _tpl_prefs.get('kleinunternehmer') == 'true'
        skonto_pct = float(_tpl_prefs['default_skonto_percent']) if _tpl_prefs.get('default_skonto_percent') else None
        skonto_days = int(_tpl_prefs['default_skonto_days']) if _tpl_prefs.get('default_skonto_days') else None

    except Exception as exc:
        logger.warning('Template-aware PDF setup failed, using legacy: %s', exc)
        # Fallback to legacy
        tenant_dict = {
            'company_name': 'Meine Firma',
            'street': '',
            'zip': '',
            'city': '',
            'iban': '',
            'bic': '',
            'tax_id': '',
        }
        template_key = 'clean'
        logo_b64 = None
        kleinunternehmer = False
        skonto_pct = None
        skonto_days = None

    # P-05: FESTER Steuersatz aus DB-Items oder Kleinunternehmer-Flag
    # NIEMALS aus Division net/tax ableiten (Rundungsfehler!)
    tax_rate = 19.0
    if kleinunternehmer:
        tax_rate = 0.0
    elif db_items_list:
        # Fester Wert aus erster Position (alle Items haben gleichen Satz)
        tax_rate = float(db_items_list[0].get('tax_rate', 19))

    invoice_dict = {
        'invoice_number': invoice_number,
        'invoice_date': invoice_date.strftime('%d.%m.%Y') if invoice_date else '',
        'due_date': due_date_val.strftime('%d.%m.%Y') if due_date_val else '',
        'net_amount': float(net_total),
        'tax_amount': 0.0 if kleinunternehmer else float(tax_total),
        'gross_amount': float(net_total) if kleinunternehmer else float(gross_total),
        'tax_rate': tax_rate,
        'payment_days': 14,
    }
    # AUFGABE 3a: Format whole-number quantities (3.0 -> 3, 2.5 -> 2.5)
    for _item in db_items_list:
        qty = _item.get('quantity', 1)
        if isinstance(qty, (int, float)) and float(qty) == int(float(qty)):
            _item['quantity'] = int(float(qty))

    # Use actual line items from DB, fallback to summary line
    if db_items_list:
        items_list = db_items_list
    else:
        items_list = [{
            'description': f'Rechnung {invoice_number}',
            'quantity': 1, 'unit': 'Stk',
            'unit_price': float(net_total),
            'tax_rate': tax_rate,
            'total_price': float(net_total) if kleinunternehmer else float(gross_total),
        }]

    # Use new template system
    try:
        from app.pdf.template_registry import render_invoice_pdf
        pdf_bytes = await render_invoice_pdf(
            template_key, invoice_dict, items_list,
            contact_dict, tenant_dict,
            logo_b64=logo_b64,
            kleinunternehmer=kleinunternehmer,
            skonto_percent=skonto_pct,
            skonto_days=skonto_days,
        )
    except Exception as exc:
        logger.warning('Template PDF generation failed, using legacy: %s', exc)
        from app.pdf.service import PdfService
        pdf_service = PdfService()
        pdf_bytes = await pdf_service.generate_invoice_pdf(
            invoice=invoice_dict, items=items_list,
            contact=contact_dict, tenant=tenant_dict,
        )

    # ZUGFeRD embedding (non-fatal)
    try:
        from app.e_invoice.generator import embed_zugferd
        pdf_bytes = embed_zugferd(pdf_bytes, {
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'due_date': due_date_val,
            'net_amount': float(net_total),
            'tax_amount': float(tax_total),
            'gross_amount': float(gross_total),
            'currency': 'EUR',
            'seller_name': tenant_dict.get('company_name', ''),
            'seller_tax_id': tenant_dict.get('tax_id', ''),
            'buyer_name': contact_dict.get('name', ''),
            'iban': tenant_dict.get('iban', ''),
            'bic': tenant_dict.get('bic', ''),
            'items': items_list,
        })
    except Exception as exc:
        logger.warning('ZUGFeRD embedding failed: %s', exc)

    return pdf_bytes
