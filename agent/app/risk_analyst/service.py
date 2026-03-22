"""Risk/Consistency Analyst — deterministic checks + optional LLM summary.

Five rule-based checks run for every case (no LLM needed).
LLM is called only when at least one MEDIUM+ finding exists, to produce
a human-readable German summary.  Falls back to a template summary on any error.

CaseConflicts are created automatically for HIGH/CRITICAL findings.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from litellm import acompletion

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

from app.case_engine.models import CaseRecord
from app.risk_analyst.rules import (
    check_amount_consistency,
    check_booking_plausibility,
    check_duplicate_detection,
    check_tax_plausibility,
    check_vendor_consistency,
)
from app.risk_analyst.schemas import (
    OverallRisk,
    RiskCheck,
    RiskReport,
    _SEVERITY_ORDER,
    compute_overall_risk,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du bist ein Risikoprüfer für Buchhaltungsvorgänge im FRYA-System.
Deine Rolle: Querprüfung, Anomalieerkennung und Konsistenzcheck.
Dein Output ist ein kurzer deutscher Text (2-4 Sätze).

Du prüfst jeden Vorschlag so, als ob er falsch sein könnte. Suche aktiv nach dem Fehler.

═══════════════════════════════════════
PRÜFSCHRITTE (alle durchgehen)
═══════════════════════════════════════

1. BETRAGSCHECK: Brutto = Netto + Steuer? Betrag weicht >10% vom Durchschnitt für diesen Kreditor ab?
2. DUPLIKAT-CHECK: Gleiche Rechnungsnummer + Betrag + Kreditor schon vorhanden?
3. STEUER-CHECK: Steuersatz plausibel für Kreditor/Dokumenttyp? Reverse Charge? Innergemeinschaftlich?
4. REFERENZ-CHECK: Referenzen zwischen Dokumentanalyse und Buchungsvorschlag konsistent?
5. VORGANGS-CHECK: Dokument passt zum zugeordneten Case? Vendor stimmt? Beträge konsistent?
6. TIMELINE-CHECK: Chronologisch plausibel? (Mahnung nach Rechnung, nicht davor.)

═══════════════════════════════════════
OUTPUT
═══════════════════════════════════════

Wenn alles konsistent: "Keine Auffälligkeiten. Vorschlag konsistent."

Wenn Anomalien gefunden: Jede konkret benennen mit Typ und Schwere.

Anomalie-Typen:
  AMOUNT_DEVIATION — Betrag weicht >10% von historischem Wert ab
  DUPLICATE_SUSPECT — Mögliches Duplikat
  TAX_INCONSISTENCY — Steuersatz passt nicht zum Kontext
  REFERENCE_MISMATCH — Referenzen stimmen nicht überein
  VENDOR_MISMATCH — Kreditor im Dokument ≠ Kreditor im Case
  TIMELINE_ANOMALY — Chronologisch unplausible Reihenfolge
  CALCULATION_ERROR — Brutto ≠ Netto + Steuer

Deine Rolle ist ausschließlich Prüfung und Befund. Buchungsvorschläge erstellt der Accounting Analyst.
Jede Auffälligkeit wird berichtet — auch wenn sie sich als harmlos herausstellen könnte.

═══════════════════════════════════════
BEISPIELE
═══════════════════════════════════════

Beispiel 1 — Alles OK:
Input: 1&1 Telecom, 8.54€, 19% MwSt, Brutto=Netto+Steuer stimmt, kein Duplikat
→ "Keine Auffälligkeiten. Vorschlag konsistent."

Beispiel 2 — Betragsabweichung:
Input: Hetzner, 24.90€ (letzter Monat: 6.38€)
→ "AMOUNT_DEVIATION (HIGH): Hetzner-Rechnung 24.90€ weicht um 290% vom historischen Durchschnitt 6.38€ ab. Bitte prüfen ob der Betrag korrekt ist."

Beispiel 3 — Duplikat:
Input: 1&1, Rechnungsnr 151122582904, bereits im System
→ "DUPLICATE_SUSPECT (HIGH): Rechnungsnummer 151122582904 von 1&1 existiert bereits als Case #xyz. Mögliches Duplikat.\""""


class RiskAnalystService:
    """Deterministic risk checks with optional LLM-generated summary."""

    def __init__(
        self,
        repo: object,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> None:
        self._repo = repo
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    async def analyze_case(self, case_id: uuid.UUID) -> RiskReport | None:
        """Run all risk checks for a single case and persist the result."""
        repo = self._repo  # type: ignore[union-attr]

        case = await repo.get_case(case_id)
        if case is None:
            return None

        documents = await repo.get_case_documents(case_id)
        all_cases = await repo.list_active_cases_for_tenant(case.tenant_id)

        checks: list[RiskCheck] = [
            check_amount_consistency(case, documents),
            check_duplicate_detection(case, all_cases),
            check_tax_plausibility(case),
            check_vendor_consistency(case, documents),
            check_booking_plausibility(case),
        ]

        overall = compute_overall_risk(checks)

        has_medium_plus = any(_SEVERITY_ORDER.get(c.severity, 0) >= 2 for c in checks)
        summary = (
            await self._make_summary(case, checks, overall)
            if has_medium_plus
            else _template_summary(checks, overall)
        )

        checked_at = datetime.now(timezone.utc).isoformat()
        report = RiskReport(
            case_id=str(case_id),
            checks=checks,
            overall_risk=overall,
            summary=summary,
            checked_at=checked_at,
        )

        # Persist report in case metadata
        try:
            await repo.update_metadata(case_id, {'risk_report': report.model_dump(mode='json')})
        except Exception as exc:
            logger.warning('risk_analyst: failed to store risk_report: %s', exc)

        # Create CaseConflicts for HIGH/CRITICAL findings
        for check in checks:
            if _SEVERITY_ORDER.get(check.severity, 0) >= 3:
                conflict_type = _check_type_to_conflict(check.check_type)
                try:
                    await repo.create_conflict(
                        case_id=case_id,
                        conflict_type=conflict_type,
                        description=check.finding,
                        metadata={
                            'severity': check.severity,
                            'check_type': check.check_type,
                            'source': 'risk-analyst-v1',
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        'risk_analyst: failed to create conflict for %s: %s',
                        check.check_type, exc,
                    )

        return report

    async def scan_all_open_cases(self, tenant_id: uuid.UUID) -> list[RiskReport]:
        """Analyze all OPEN/OVERDUE cases for a tenant, sorted by risk level."""
        repo = self._repo  # type: ignore[union-attr]
        cases = await repo.list_active_cases_for_tenant(tenant_id)

        reports: list[RiskReport] = []
        for case in cases:
            report = await self.analyze_case(case.id)
            if report is not None:
                reports.append(report)

        _risk_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'OK': 3}
        reports.sort(key=lambda r: _risk_order.get(r.overall_risk, 9))
        return reports

    async def _make_summary(
        self,
        case: CaseRecord,
        checks: list[RiskCheck],
        overall: OverallRisk,
    ) -> str:
        if not self._api_key:
            return _template_summary(checks, overall)
        try:
            return await self._llm_summary(case, checks, overall)
        except Exception as exc:
            logger.warning('risk_analyst LLM call failed — using template: %s', exc)
            return _template_summary(checks, overall)

    async def _llm_summary(
        self,
        case: CaseRecord,
        checks: list[RiskCheck],
        overall: OverallRisk,
    ) -> str:
        problems = [
            f'- [{c.severity}] {c.check_type}: {c.finding}'
            for c in checks
            if _SEVERITY_ORDER.get(c.severity, 0) >= 2
        ]
        user_content = (
            f'Vorgang: {case.case_number or str(case.id)}\n'
            f'Typ: {case.case_type}\n'
            f'Vendor: {case.vendor_name or "unbekannt"}\n'
            f'Betrag: {case.total_amount} {case.currency}\n'
            f'Gesamtrisiko: {overall}\n'
            f'Befunde:\n' + '\n'.join(problems)
        )

        call_kwargs: dict = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
            'max_tokens': 256,
            'temperature': 0.1,
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

def _template_summary(checks: list[RiskCheck], overall: OverallRisk) -> str:
    if overall == 'OK':
        return 'Keine Risiken gefunden — Vorgang ist konsistent.'

    parts: list[str] = []

    high_crit = [c for c in checks if _SEVERITY_ORDER.get(c.severity, 0) >= 3]
    medium = [c for c in checks if c.severity == 'MEDIUM']

    if high_crit:
        types = ', '.join(c.check_type for c in high_crit)
        parts.append(f'{len(high_crit)} kritischer/hoher Befund(e): {types}.')
    if medium:
        parts.append(f'{len(medium)} mittlerer Befund(e) vorhanden.')

    parts.append(f'Gesamtrisiko: {overall}.')
    return ' '.join(parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_risk_analyst_service(
    repo: object,
    llm_repo: object | None,
    config: dict | None,
) -> RiskAnalystService:
    """Build service from LLMConfigRepository config dict.

    Returns a deterministic-only service (no LLM) when repo/config/key is absent.
    """
    model_str = ''
    api_key: str | None = None
    base_url: str | None = None

    if llm_repo is not None and config is not None:
        model_str = (config.get('model') or '').strip()
        base_url = config.get('base_url') or None
        if model_str:
            try:
                api_key = llm_repo.decrypt_key_for_call(config)  # type: ignore[union-attr]
            except Exception:
                api_key = None
        if model_str and api_key:
            provider = (config.get('provider') or '').strip()
            if provider == 'ionos':
                full_model = f'openai/{model_str}'
            elif provider and '/' not in model_str:
                full_model = f'{provider}/{model_str}'
            else:
                full_model = model_str
            return RiskAnalystService(
                repo=repo, model=full_model, api_key=api_key, base_url=base_url
            )

    return RiskAnalystService(repo=repo, model='', api_key=None, base_url=None)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _check_type_to_conflict(check_type: str) -> str:
    """Map risk check_type to a valid CaseConflict conflict_type."""
    mapping = {
        'amount_consistency': 'amount_mismatch',
        'duplicate_detection': 'duplicate_case',
        'tax_plausibility': 'amount_mismatch',
        'vendor_consistency': 'vendor_mismatch',
        'booking_plausibility': 'amount_mismatch',
    }
    return mapping.get(check_type, 'amount_mismatch')
