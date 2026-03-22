"""Deadline Analyst — Fristüberwachung für CaseEngine-Cases.

- Erkennt überfällige Cases, heute fällige und bald fällige.
- Setzt OPEN-Cases mit abgelaufener Frist automatisch auf OVERDUE.
- Warnt bei ablaufendem Skonto (aus case.metadata).
- Generiert LLM-Zusammenfassung (Mistral-Small-24B/IONOS); Fallback auf Template.
- OVERDUE-Setzung: OPEN→OVERDUE braucht kein operator=True (laut status.py).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from litellm import acompletion

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

from app.case_engine.models import CaseRecord
from app.case_engine.repository import CaseRepository
from app.deadline_analyst.schemas import (
    DeadlineCheck,
    DeadlineReport,
    FristConfig,
    SkontoInfo,
)

logger = logging.getLogger(__name__)


class DeadlineAnalystService:
    """Fristüberwachungs-Service für CaseEngine-Cases."""

    def __init__(
        self,
        repo: CaseRepository,
        model: str,
        api_key: str | None,
        base_url: str | None,
        config: FristConfig | None = None,
    ) -> None:
        self._repo = repo
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._config = config or FristConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_all_deadlines(self, tenant_id: uuid.UUID) -> DeadlineReport:
        """Scan all active cases for deadline issues; auto-set OVERDUE where needed."""
        today = date.today()
        now = datetime.now(timezone.utc)

        cases = await self._repo.list_active_cases_for_tenant(tenant_id)
        cases_with_due = [c for c in cases if c.due_date is not None]

        overdue: list[DeadlineCheck] = []
        due_today: list[DeadlineCheck] = []
        due_soon: list[DeadlineCheck] = []
        skonto_expiring: list[DeadlineCheck] = []

        for case in cases_with_due:
            check = self._analyze_case(case, today)

            # Auto-set OPEN → OVERDUE when due_date is in the past
            if case.due_date < today and case.status == 'OPEN':
                try:
                    await self._repo.update_case_status(case.id, 'OVERDUE')
                    check = check.model_copy(update={'status': 'OVERDUE'})
                    logger.info('Case %s set to OVERDUE (due_date=%s)', case.id, case.due_date)
                except Exception as exc:
                    logger.warning('Could not set OVERDUE for case %s: %s', case.id, exc)

            # Write deadline metadata back to case
            try:
                await self._repo.update_metadata(case.id, {
                    'deadline_last_checked': now.isoformat(),
                    'deadline_priority': check.priority,
                })
            except Exception as exc:
                logger.warning('Could not update deadline metadata for %s: %s', case.id, exc)

            # Categorise
            if check.warning_type == 'overdue':
                overdue.append(check)
            elif check.warning_type == 'due_today':
                due_today.append(check)
            elif check.warning_type in ('due_soon', 'escalation'):
                due_soon.append(check)

            # Separate skonto check
            if (
                check.skonto_info is not None
                and check.skonto_info.days_until_expiry <= self._config.skonto_warning_days
            ):
                skonto_expiring.append(check.model_copy(
                    update={'warning_type': 'skonto_expiring', 'priority': 'HIGH'}
                ))

        # Sort lists: most urgent first
        overdue.sort(key=lambda c: c.days_until_due)
        due_today.sort(key=lambda c: -(c.amount or Decimal('0')))
        due_soon.sort(key=lambda c: c.days_until_due)

        total_overdue_amount = (
            sum((c.amount for c in overdue if c.amount), Decimal('0')) or None
        )

        summary = await self._make_summary(overdue, due_today, due_soon, skonto_expiring)

        return DeadlineReport(
            tenant_id=str(tenant_id),
            checked_at=now.isoformat(),
            total_cases_checked=len(cases_with_due),
            overdue=overdue,
            due_today=due_today,
            due_soon=due_soon,
            skonto_expiring=skonto_expiring,
            summary_text=summary,
            total_overdue_amount=total_overdue_amount,
        )

    async def check_single_case(self, case_id: uuid.UUID) -> DeadlineCheck | None:
        """Analyse a single case. Returns None if the case has no due_date."""
        case = await self._repo.get_case(case_id)
        if case is None or case.due_date is None:
            return None
        return self._analyze_case(case, date.today())

    async def get_skonto_info(self, case_id: uuid.UUID) -> SkontoInfo | None:
        """Return skonto info from case.metadata, or None if not present."""
        case = await self._repo.get_case(case_id)
        if case is None:
            return None
        return self._get_skonto_from_metadata(case, date.today())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_case(self, case: CaseRecord, today: date) -> DeadlineCheck:
        days = (case.due_date - today).days  # type: ignore[operator]

        if days < 0:
            priority, warning_type = 'CRITICAL', 'overdue'
        elif days == 0:
            priority, warning_type = 'HIGH', 'due_today'
        elif days <= self._config.due_soon_days:
            priority, warning_type = 'MEDIUM', 'due_soon'
        else:
            priority, warning_type = 'LOW', 'due_soon'

        # Escalate if overdue for a long time
        if days < -self._config.escalation_after_days:
            warning_type = 'escalation'

        skonto_info = self._get_skonto_from_metadata(case, today)

        return DeadlineCheck(
            case_id=str(case.id),
            case_number=case.case_number,
            vendor_name=case.vendor_name,
            amount=case.total_amount,
            currency=case.currency,
            due_date=case.due_date,
            days_until_due=days,
            skonto_info=skonto_info,
            priority=priority,
            warning_type=warning_type,
            status=case.status,
        )

    def _get_skonto_from_metadata(self, case: CaseRecord, today: date) -> SkontoInfo | None:
        meta = case.metadata or {}
        skonto_rate = meta.get('skonto_rate')
        if not skonto_rate:
            return None

        skonto_date_str = meta.get('skonto_date')
        skonto_days_raw = meta.get('skonto_days')

        try:
            if skonto_date_str:
                skonto_date = date.fromisoformat(str(skonto_date_str))
            elif skonto_days_raw and case.due_date:
                # Estimate: invoice_date = due_date - 30; skonto ends at invoice_date + skonto_days
                skonto_date = case.due_date  # conservative fallback
            else:
                return None
        except (ValueError, TypeError):
            return None

        days_until_expiry = (skonto_date - today).days
        skonto_amount: Decimal | None = None
        try:
            if case.total_amount:
                skonto_amount = (
                    case.total_amount * Decimal(str(skonto_rate)) / Decimal('100')
                ).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            pass

        return SkontoInfo(
            skonto_rate=float(skonto_rate),
            skonto_days=int(skonto_days_raw) if skonto_days_raw else 0,
            skonto_date=skonto_date,
            skonto_amount=skonto_amount,
            days_until_expiry=days_until_expiry,
        )

    async def _make_summary(
        self,
        overdue: list[DeadlineCheck],
        due_today: list[DeadlineCheck],
        due_soon: list[DeadlineCheck],
        skonto_expiring: list[DeadlineCheck],
    ) -> str:
        if self._api_key:
            try:
                return await self._llm_summary(overdue, due_today, due_soon, skonto_expiring)
            except Exception as exc:
                logger.warning('deadline_analyst LLM summary failed — using template: %s', exc)
        return _template_summary(overdue, due_today, due_soon, skonto_expiring)

    async def _llm_summary(
        self,
        overdue: list[DeadlineCheck],
        due_today: list[DeadlineCheck],
        due_soon: list[DeadlineCheck],
        skonto_expiring: list[DeadlineCheck],
    ) -> str:
        _system = (
            'Du bist der Frist-Analyst von FRYA. Deine Aufgabe: Fristen und Termine in einer kurzen Zusammenfassung darstellen.\n'
            'Dein Output ist ausschließlich reiner deutscher Text (2 Sätze). Kein JSON, kein Markdown, keine Aufzählung.\n\n'
            'Prioritäten:\n'
            '- Einspruchsfristen (OBJECTION) sind IMMER die höchste Priorität. Benenne sie zuerst.\n'
            '- Skonto-Fristen sind wichtig — Geld sparen ist relevant.\n'
            '- Überfällige Rechnungen vor bald fälligen.\n\n'
            'Beispiel 1 — Mehrere Fristen:\n'
            'Input: 2 überfällig, 1 heute fällig, 3 Skonto läuft ab\n'
            '→ "Zwei Vorgänge sind überfällig und einer ist heute fällig. Außerdem laufen drei Skonto-Fristen in den nächsten Tagen ab."\n\n'
            'Beispiel 2 — Alles im grünen Bereich:\n'
            'Input: 0 überfällig, 0 heute fällig, 0 Skonto\n'
            '→ "Alle Fristen sind im grünen Bereich."'
        )
        prompt = (
            'Erstelle eine kurze deutsche Zusammenfassung (max 2 Sätze) der Fristensituation:\n'
            f'- Überfällig: {len(overdue)} Fälle\n'
            f'- Heute fällig: {len(due_today)} Fälle\n'
            f'- Diese Woche fällig: {len(due_soon)} Fälle\n'
            f'- Skonto läuft ab: {len(skonto_expiring)} Fälle\n'
            'Antworte mit reinem Text, ohne Aufzählung, ohne Markdown.'
        )
        call_kwargs: dict = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': _system},
                {'role': 'user', 'content': prompt},
            ],
            'max_tokens': 150,
            'temperature': 0.3,
            'timeout': _LLM_TIMEOUT,
        }
        if self._api_key:
            call_kwargs['api_key'] = self._api_key
        if self._base_url:
            call_kwargs['api_base'] = self._base_url

        completion = await acompletion(**call_kwargs)
        return (completion.choices[0].message.content or '').strip()


# ---------------------------------------------------------------------------
# Template summary (no LLM)
# ---------------------------------------------------------------------------

def _template_summary(
    overdue: list[DeadlineCheck],
    due_today: list[DeadlineCheck],
    due_soon: list[DeadlineCheck],
    skonto_expiring: list[DeadlineCheck],
) -> str:
    if not any([overdue, due_today, due_soon, skonto_expiring]):
        return 'Alle Fristen im gruenen Bereich.'
    parts = []
    if overdue:
        amt = sum((c.amount for c in overdue if c.amount), Decimal('0'))
        parts.append(
            f'{len(overdue)} Vorgang/Vorgaenge ueberfaellig (Summe: {amt:.2f} EUR)'
        )
    if due_today:
        parts.append(f'{len(due_today)} heute faellig')
    if due_soon:
        parts.append(f'{len(due_soon)} in Kuerze faellig')
    if skonto_expiring:
        parts.append(f'{len(skonto_expiring)} Skonto laeuft ab')
    return '. '.join(parts) + '.'


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_deadline_analyst_service(
    repo: CaseRepository,
    llm_repo: object | None,
    llm_config: dict | None,
    frist_config: FristConfig | None = None,
) -> DeadlineAnalystService:
    """Build service from LLMConfigRepository config dict."""
    model_str = ''
    api_key: str | None = None
    base_url: str | None = None

    if llm_repo is not None and llm_config is not None:
        model_str = (llm_config.get('model') or '').strip()
        base_url = llm_config.get('base_url') or None
        if model_str:
            try:
                api_key = llm_repo.decrypt_key_for_call(llm_config)  # type: ignore[union-attr]
            except Exception:
                api_key = None
        if model_str and api_key:
            provider = (llm_config.get('provider') or '').strip()
            if provider == 'ionos':
                model_str = f'openai/{model_str}'
            elif provider and '/' not in model_str:
                model_str = f'{provider}/{model_str}'

    return DeadlineAnalystService(
        repo=repo,
        model=model_str,
        api_key=api_key,
        base_url=base_url,
        config=frist_config,
    )
