"""Full service registry for ActionRouter — all 14 handlers wired.

Each method wraps existing API/service logic so ActionRouter can call
them directly without going through HTTP endpoints.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


async def _resolve_tenant(tenant_id: str | None = None) -> uuid.UUID:
    """Resolve tenant UUID. P-17: Prefer explicit tenant_id from caller (JWT).

    P-34 FIX: Non-UUID strings like 'default' are converted via uuid5
    (same logic as bulk_upload._get_tenant_id) instead of raising RuntimeError.
    """
    if tenant_id:
        try:
            return uuid.UUID(str(tenant_id))
        except ValueError:
            # Non-UUID string (e.g. 'default') — deterministic UUID, consistent
            # with bulk_upload._get_tenant_id() last-resort fallback
            return uuid.uuid5(uuid.NAMESPACE_DNS, str(tenant_id))
    # Fallback for non-authenticated contexts (webhooks, cron)
    from app.case_engine.tenant_resolver import resolve_tenant_id
    logger.warning('P-17: service_registry using resolve_tenant_id() fallback — no tenant_id in caller context')
    tid = await resolve_tenant_id()
    if tid:
        return uuid.UUID(tid)
    raise RuntimeError('tenant_unavailable')


def _get_repo():
    from app.dependencies import get_accounting_repository
    return get_accounting_repository()


def _get_booking_svc():
    from app.accounting.booking_service import BookingService
    return BookingService(_get_repo())


# ─── Inbox (approve / reject / defer / list_pending) ──────────────────────

class _InboxService:
    async def approve(self, case_id: str = '', **kw) -> dict:
        """Approve a case — reuses BookingApprovalService logic."""
        from app.accounting.booking_service import BookingService
        from app.booking.approval_service import BookingApprovalService
        from app.dependencies import (
            get_accounting_repository, get_approval_service,
            get_audit_service, get_open_items_service,
        )
        approval_svc = get_approval_service()
        # P-12: Try UUID first, then resolve via case_documents (doc-X format)
        pending = [r for r in await approval_svc.list_by_case(case_id)
                   if r.status == 'PENDING' and r.action_type == 'booking_finalize']
        if not pending:
            # Approvals use doc-{paperless_id} as case_id — resolve via case_documents
            # P-25b: A case can have multiple document_source_ids — check ALL of them
            try:
                import asyncpg
                from app.dependencies import get_settings
                conn = await asyncpg.connect(get_settings().database_url)
                try:
                    doc_rows = await conn.fetch(
                        "SELECT document_source_id FROM case_documents WHERE case_id = $1::uuid ORDER BY document_source_id::int DESC",
                        case_id,
                    )
                    for doc_row in doc_rows:
                        if doc_row['document_source_id']:
                            doc_case_id = f"doc-{doc_row['document_source_id']}"
                            pending = [r for r in await approval_svc.list_by_case(doc_case_id)
                                       if r.status == 'PENDING' and r.action_type == 'booking_finalize']
                            if pending:
                                case_id = doc_case_id  # Use doc-X for downstream
                                break
                finally:
                    await conn.close()
            except Exception as exc:
                logger.warning('Approval doc-ID resolve failed: %s', exc)
        if not pending:
            return {'status': 'no_pending', 'message': 'Keine offene Freigabe für diesen Beleg.'}

        svc = BookingApprovalService(
            approval_service=approval_svc, open_items_service=get_open_items_service(),
            audit_service=get_audit_service(), booking_service=BookingService(get_accounting_repository()),
        )
        result = await svc.process_response(
            case_id=case_id, approval_id=pending[0].approval_id,
            decision_raw='APPROVE', decided_by='user', source='action_router',
        )
        # Get next pending item
        next_item = await self._get_next_pending(case_id)
        return {'status': 'approved', 'result': result, 'next_item': next_item}

    async def reject(self, case_id: str = '', **kw) -> dict:
        from app.dependencies import get_approval_service
        approval_svc = get_approval_service()
        pending = [r for r in await approval_svc.list_by_case(case_id)
                   if r.status == 'PENDING']
        # P-12/P-25b: Resolve via doc-X if UUID lookup fails — check ALL doc IDs
        if not pending:
            try:
                import asyncpg
                from app.dependencies import get_settings
                conn = await asyncpg.connect(get_settings().database_url)
                try:
                    doc_rows = await conn.fetch(
                        "SELECT document_source_id FROM case_documents WHERE case_id = $1::uuid ORDER BY document_source_id::int DESC",
                        case_id,
                    )
                    for doc_row in doc_rows:
                        if doc_row['document_source_id']:
                            doc_case_id = f"doc-{doc_row['document_source_id']}"
                            pending = [r for r in await approval_svc.list_by_case(doc_case_id)
                                       if r.status == 'PENDING']
                            if pending:
                                case_id = doc_case_id
                                break
                finally:
                    await conn.close()
            except Exception:
                pass
        if pending:
            from app.booking.approval_service import BookingApprovalService
            from app.dependencies import get_audit_service, get_open_items_service
            svc = BookingApprovalService(
                approval_service=approval_svc, open_items_service=get_open_items_service(),
                audit_service=get_audit_service(), booking_service=_get_booking_svc(),
            )
            await svc.process_response(
                case_id=case_id, approval_id=pending[0].approval_id,
                decision_raw='REJECT', decided_by='user', source='action_router',
            )
        return {'status': 'rejected'}

    async def defer(self, case_id: str = '', **kw) -> dict:
        next_item = await self._get_next_pending(case_id)
        return {'status': 'deferred', 'next_item': next_item}

    async def list_pending(self, **kw) -> dict:
        """List pending inbox items — same logic as GET /inbox."""
        from app.dependencies import get_case_repository
        tid = await _resolve_tenant(kw.get('tenant_id'))
        repo = get_case_repository()
        cases = await repo.list_active_cases_for_tenant(tid)
        try:
            drafts = await repo.list_cases_by_status(tid, 'DRAFT')
            seen = {c.id for c in cases}
            for d in drafts:
                if d.id not in seen:
                    cases.append(d)
        except Exception:
            pass
        pending = [c for c in cases if c.status in ('DRAFT', 'OPEN')]
        pending.sort(key=lambda c: c.created_at or __import__('datetime').datetime.min, reverse=True)

        items = []
        for c in pending[:20]:
            meta = c.metadata or {}
            doc_analysis = meta.get('document_analysis', {})
            # overall_confidence lives inside document_analysis sub-dict
            conf = doc_analysis.get('overall_confidence') or meta.get('overall_confidence')
            items.append({
                'case_id': str(c.id), 'vendor': c.vendor_name or '?',
                'amount': float(c.total_amount) if c.total_amount else None,
                'document_type': doc_analysis.get('document_type', ''),
                'confidence': conf,
                'confidence_label': 'Sicher' if (conf or 0) >= 0.85 else 'Hoch' if (conf or 0) >= 0.65 else 'Mittel' if (conf or 0) >= 0.4 else 'Niedrig',
                'status': c.status,
            })

        # P-25: Load references for grouping
        references = []
        try:
            import uuid as _uuid
            for c in pending[:20]:
                refs = await repo.get_case_references(_uuid.UUID(str(c.id)))
                for r in refs:
                    references.append({
                        'case_id': str(r.case_id),
                        'reference_type': r.reference_type,
                        'reference_value': r.reference_value,
                    })
        except Exception as _ref_exc:
            logger.debug('Could not load case references for grouping: %s', _ref_exc)

        return {'items': items, 'count': len(pending), 'references': references}

    async def get_case(self, case_id: str = '', **kw) -> dict:
        """Load a single case by case_id for detail view (P-25)."""
        from app.dependencies import get_case_repository
        import uuid as _uuid
        repo = get_case_repository()
        try:
            case = await repo.get_case(_uuid.UUID(case_id))
        except Exception:
            return {'error': f'Vorgang {case_id} nicht gefunden.'}
        if not case:
            return {'error': f'Vorgang {case_id} nicht gefunden.'}
        meta = case.metadata or {}
        doc_analysis = meta.get('document_analysis', {})
        conf = doc_analysis.get('overall_confidence') or meta.get('overall_confidence')
        fields = doc_analysis.get('fields', {})
        # Build rich detail response
        result = {
            'case': {
                'id': str(case.id),
                'case_number': getattr(case, 'case_number', str(case.id)[:13]),
                'case_type': doc_analysis.get('document_type', ''),
                'vendor_name': case.vendor_name or '?',
                'total_amount': float(case.total_amount) if case.total_amount else 0,
                'status': case.status,
                'confidence': conf,
                'confidence_label': 'Sicher' if (conf or 0) >= 0.85 else 'Hoch' if (conf or 0) >= 0.65 else 'Mittel' if (conf or 0) >= 0.4 else 'Niedrig',
            },
            'fields': fields,
            'document_analysis': doc_analysis,
        }
        # Load references
        try:
            refs = await repo.get_case_references(_uuid.UUID(case_id))
            result['references'] = [
                {'type': r.reference_type, 'value': r.reference_value}
                for r in refs
            ]
        except Exception:
            result['references'] = []
        return result

    async def process_first(self, **kw) -> dict:
        """Zeige den ersten Beleg aus der Inbox fuer den Abarbeiten-Modus."""
        tid = await _resolve_tenant(kw.get('tenant_id'))
        from app.dependencies import get_case_repository
        repo = get_case_repository()
        # Alle aktiven/offenen Cases laden
        try:
            cases = await repo.list_active_cases_for_tenant(tid)
        except Exception:
            cases = []
        try:
            drafts = await repo.list_cases_by_status(tid, 'DRAFT')
            seen = {c.id for c in cases}
            for d in drafts:
                if d.id not in seen:
                    cases.append(d)
        except Exception:
            pass
        pending = [c for c in cases if c.status in ('DRAFT', 'OPEN')]
        pending.sort(key=lambda c: c.created_at or __import__('datetime').datetime.min, reverse=True)
        if not pending:
            return {'status': 'empty', 'count': 0}
        first = pending[0]
        meta = first.metadata or {}
        doc_analysis = meta.get('document_analysis', {})
        conf = doc_analysis.get('overall_confidence') or meta.get('overall_confidence')
        first_dict = {
            'case_id': str(first.id),
            'vendor': first.vendor_name or '?',
            'amount': float(first.total_amount) if first.total_amount else None,
            'document_type': doc_analysis.get('document_type', ''),
            'confidence': conf,
            'confidence_label': 'Sicher' if (conf or 0) >= 0.85 else 'Hoch' if (conf or 0) >= 0.65 else 'Mittel' if (conf or 0) >= 0.4 else 'Niedrig',
            'status': first.status,
            'fields': doc_analysis.get('fields', {}),
        }
        return {
            'status': 'has_items',
            'count': len(pending),
            'current_index': 0,
            'current_item': first_dict,
        }

    async def _get_next_pending(self, skip_case_id: str = '') -> dict | None:
        try:
            result = await self.list_pending()
            for item in result.get('items', []):
                if item.get('case_id') != skip_case_id:
                    return item
        except Exception:
            pass
        return None


# ─── Deadlines ────────────────────────────────────────────────────────────

class _DeadlineService:
    async def list(self, **kw) -> dict:
        """Same as GET /deadlines — wraps deadline_analyst_service."""
        from app.deadline_analyst.service import build_deadline_analyst_service
        from app.dependencies import get_case_repository, get_llm_config_repository
        tid = await _resolve_tenant(kw.get('tenant_id'))
        llm_repo = get_llm_config_repository()
        llm_config = None
        if llm_repo:
            try:
                llm_config = await llm_repo.get_config_or_fallback('deadline_analyst')
            except Exception:
                pass
        svc = build_deadline_analyst_service(get_case_repository(), llm_repo, llm_config)
        report = await svc.check_all_deadlines(tid)
        def _item(it: Any) -> dict:
            return {
                'case_id': str(getattr(it, 'case_id', '')),
                'vendor_name': getattr(it, 'vendor_name', None),
                'amount': float(getattr(it, 'amount', 0)) if getattr(it, 'amount', None) else None,
                'due_date': str(getattr(it, 'due_date', '')),
                'days_remaining': getattr(it, 'days_remaining', None),
            }
        deadlines = []
        for group in ['overdue', 'due_today', 'due_soon', 'skonto_expiring']:
            for it in getattr(report, group, None) or []:
                d = _item(it)
                d['group'] = group
                deadlines.append(d)
        return {'deadlines': deadlines, 'summary': getattr(report, 'summary', '')}


# ─── Finance ──────────────────────────────────────────────────────────────

class _FinanceService:
    async def get_finance_summary(self, **kw) -> dict:
        tid = await _resolve_tenant(kw.get('tenant_id'))
        svc = _get_booking_svc()
        year = kw.get('year', date.today().year)
        return await svc.get_finance_summary(
            tid, date_from=date(year, 1, 1), date_to=date(year, 12, 31),
        )

    async def export_datev(self, **kw) -> dict:
        return {'url': f'/api/v1/export/datev?year={kw.get("year", date.today().year)}'}


# ─── Bookings / Open Items / Contacts ─────────────────────────────────────

class _BookingService:
    async def list(self, **kw) -> dict:
        tid = await _resolve_tenant(kw.get('tenant_id'))
        bookings = await _get_repo().list_bookings(tid, limit=kw.get('limit', 20))
        return {'items': [b.model_dump(mode='json') for b in bookings], 'count': len(bookings)}


class _OpenItemService:
    async def list(self, **kw) -> dict:
        tid = await _resolve_tenant(kw.get('tenant_id'))
        items = await _get_repo().list_open_items(tid)
        return {'items': [i.model_dump(mode='json') for i in items], 'count': len(items)}


class _ContactService:
    async def get_dossier(self, contact_id: str = '', **kw) -> dict:
        tid = await _resolve_tenant(kw.get('tenant_id'))
        repo = _get_repo()
        contact = await repo.get_contact_by_id(tid, uuid.UUID(contact_id))
        if not contact:
            return {'error': 'Kontakt nicht gefunden'}
        bookings = await repo.list_bookings(tid, limit=10000)
        cb = [b for b in bookings if b.contact_id == contact_id]
        return {
            'dossier': {
                'contact': contact.model_dump(mode='json'),
                'stats': {
                    'total_revenue': sum(float(b.gross_amount) for b in cb if b.booking_type == 'INCOME'),
                    'total_expenses': sum(float(b.gross_amount) for b in cb if b.booking_type == 'EXPENSE'),
                    'open_amount': 0, 'booking_count': len(cb),
                },
            }
        }


# ─── Invoice ──────────────────────────────────────────────────────────────

class _InvoiceService:
    async def prepare_form(self, contact_name: str = '', **kw) -> dict:
        from app.services.form_builders import build_invoice_form
        contact = None
        if contact_name:
            tid = await _resolve_tenant(kw.get('tenant_id'))
            contacts = await _get_repo().list_contacts(tid)
            contact = next((c for c in contacts if contact_name.lower() in c.name.lower()), None)
        form = build_invoice_form(contact=contact)
        return {'form': form}

    async def finalize(self, invoice_id: str = '', **kw) -> dict:
        return {'url': f'/api/v1/invoices/{invoice_id}/finalize', 'method': 'POST'}


# ─── Settings ─────────────────────────────────────────────────────────────

class _SettingsService:
    async def get(self, user_id: str = '', **kw) -> dict:
        from app.dependencies import get_settings
        import asyncpg
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return {}
        try:
            conn = await asyncpg.connect(settings.database_url)
            try:
                rows = await conn.fetch(
                    "SELECT key, value FROM frya_user_preferences WHERE user_id = $1",
                    user_id or 'testkunde',
                )
                prefs = {r['key']: r['value'] for r in rows}
                result = {
                    'display_name': prefs.get('display_name', ''),
                    'theme': prefs.get('theme', 'system'),
                    'formal_address': prefs.get('formal_address', 'false') == 'true',
                    'notification_channel': prefs.get('notification_channel', 'in_app'),
                }
                # Load business profile from frya_business_profile
                try:
                    bp_row = await conn.fetchrow(
                        "SELECT * FROM frya_business_profile "
                        "WHERE user_id = $1 "
                        "ORDER BY updated_at DESC NULLS LAST LIMIT 1",
                        user_id or 'testkunde',
                    )
                    if bp_row:
                        result['business_profile'] = dict(bp_row)
                except Exception as bp_exc:
                    logger.warning('Business profile load in settings failed: %s', bp_exc)
                return result
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('SettingsService.get failed: %s', exc)
            return {}

    async def update(self, key: str = '', value: str = '', user_id: str = '', **kw) -> dict:
        from app.dependencies import get_settings
        import asyncpg
        settings = get_settings()
        if settings.database_url.startswith('memory://'):
            return {'status': 'skipped'}
        allowed = {'display_name', 'theme', 'formal_address', 'notification_channel', 'emoji_enabled'}
        if key not in allowed:
            return {'status': 'rejected', 'reason': f'Key {key} nicht erlaubt'}
        # P-06: Validate display_name before saving
        if key == 'display_name':
            from app.api.chat_ws import is_plausible_name
            is_name, conf = is_plausible_name(str(value))
            if not is_name or conf < 0.6:
                return {'status': 'rejected', 'reason': 'Kein plausibler Name'}
            value = str(value).strip().title()
        try:
            conn = await asyncpg.connect(settings.database_url)
            try:
                await conn.execute(
                    """INSERT INTO frya_user_preferences (tenant_id, user_id, key, value, updated_at)
                    VALUES ('default', $1, $2, $3, NOW())
                    ON CONFLICT (tenant_id, user_id, key) DO UPDATE
                      SET value = EXCLUDED.value, updated_at = NOW()""",
                    user_id or 'testkunde', key, str(value),
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('SettingsService.update failed: %s', exc)
            return {'status': 'error'}
        return {'status': 'ok', 'key': key, 'value': value}


# ─── Case ─────────────────────────────────────────────────────────────────

class _CaseService:
    async def mark_private(self, case_id: str = '', **kw) -> dict:
        """Mark a case as private (tag-based)."""
        # Minimal: set metadata.private = true
        from app.dependencies import get_settings
        import asyncpg
        settings = get_settings()
        try:
            conn = await asyncpg.connect(settings.database_url)
            try:
                await conn.execute(
                    "UPDATE frya_cases SET metadata = jsonb_set(COALESCE(metadata,'{}'), '{private}', 'true') WHERE id = $1::uuid",
                    case_id,
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('mark_private failed: %s', exc)
            return {'status': 'error'}
        return {'status': 'private', 'case_id': case_id}


# ─── Build Registry ──────────────────────────────────────────────────────

def build_service_registry() -> dict:
    """Build a complete service registry for ActionRouter (14/14 handlers)."""
    return {
        'inbox_service': _InboxService(),
        'deadline_service': _DeadlineService(),
        'euer_service': _FinanceService(),
        'booking_service': _BookingService(),
        'open_item_service': _OpenItemService(),
        'contact_service': _ContactService(),
        'invoice_service': _InvoiceService(),
        'settings_service': _SettingsService(),
        'case_service': _CaseService(),
    }
