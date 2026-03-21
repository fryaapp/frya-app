from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.accounting_analysis.models import (
    AccountingAnalysisInput,
    AccountingAnalysisResult,
    AccountingField,
    AccountingRisk,
    AmountSummary,
    BookingCandidate,
    TaxHint,
)
from app.document_analysis.models import DetectedAmount, DocumentRisk, ExtractedField


class AccountingAnalysisService:
    async def analyze(self, payload: AccountingAnalysisInput) -> AccountingAnalysisResult:
        review = payload.review_draft
        analysis = payload.document_analysis_result
        review_ref = payload.accounting_review_ref

        risks = [self._map_document_risk(risk) for risk in analysis.risks]
        missing_fields: list[str] = []

        counterparty = self._string_field(review.sender, analysis.sender.evidence_excerpt)
        invoice_reference = self._reference_field(review.references, analysis.references)
        amount_summary = self._amount_summary(review.total_amount, review.currency, analysis.amounts)
        due_date_hint = self._date_field(review.due_date, analysis.due_date.evidence_excerpt)
        tax_hint, tax_risks = self._tax_hint(analysis.amounts, amount_summary)
        risks.extend(tax_risks)

        if review.review_status != 'READY' or not review.ready_for_accounting_review:
            risks.append(
                AccountingRisk(
                    code='REVIEW_NOT_READY',
                    severity='HIGH',
                    message='Accounting Review Draft ist noch nicht fuer den Accounting Analyst freigegeben.',
                    related_fields=['review_status'],
                )
            )

        if analysis.document_type.value == 'INVOICE':
            for field_name, field in (
                ('supplier_or_counterparty_hint', counterparty),
                ('invoice_reference_hint', invoice_reference),
                ('total_amount', amount_summary.total_amount),
                ('currency', amount_summary.currency),
            ):
                if field.status != 'FOUND':
                    missing_fields.append(field_name)
            if analysis.document_date.status != 'FOUND':
                missing_fields.append('document_date')
        elif analysis.document_type.value == 'REMINDER':
            for field_name, field in (
                ('supplier_or_counterparty_hint', counterparty),
                ('invoice_reference_hint', invoice_reference),
                ('total_amount', amount_summary.total_amount),
                ('currency', amount_summary.currency),
                ('due_date_hint', due_date_hint),
            ):
                if field.status != 'FOUND':
                    missing_fields.append(field_name)
            risks.append(
                AccountingRisk(
                    code='REMINDER_REQUIRES_REFERENCE_REVIEW',
                    severity='INFO',
                    message='Mahnungen werden in V1 nur als Referenz- und Faelligkeitspruefung vorgeschlagen.',
                    related_fields=['invoice_reference_hint', 'due_date_hint'],
                )
            )
        else:
            risks.append(
                AccountingRisk(
                    code='UNSUPPORTED_REVIEW_SCOPE',
                    severity='HIGH',
                    message='Accounting Analyst V1 arbeitet nur auf INVOICE- oder REMINDER-Review-Drafts.',
                    related_fields=['booking_candidate_type'],
                )
            )

        high_risks = [risk for risk in risks if risk.severity == 'HIGH']
        booking_candidate_type = 'NO_CANDIDATE'
        booking_candidate = None
        booking_confidence = 0.0
        ready_for_accounting_confirmation = False
        suggested_next_step = 'HUMAN_REVIEW'
        global_decision = 'BLOCKED_FOR_REVIEW'

        if analysis.document_type.value == 'INVOICE' and review.review_status == 'READY' and not high_risks and not missing_fields:
            booking_candidate_type = 'INVOICE_STANDARD_EXPENSE'
            booking_confidence = round(min(analysis.overall_confidence, 0.88), 3)
            ready_for_accounting_confirmation = tax_hint.rate.status == 'FOUND' and booking_confidence >= 0.8
            suggested_next_step = 'ACCOUNTING_CONFIRMATION' if ready_for_accounting_confirmation else 'HUMAN_REVIEW'
            global_decision = 'PROPOSED' if ready_for_accounting_confirmation else 'LOW_CONFIDENCE'
            booking_candidate = BookingCandidate(
                candidate_type=booking_candidate_type,
                counterparty_hint=counterparty.value,
                invoice_reference_hint=invoice_reference.value,
                review_focus=[
                    'Gegenpartei und Rechnungsreferenz gegen Originaldokument bestaetigen.',
                    'Betrag, Steuerhinweis und Belegdatum vor manueller Weiterarbeit pruefen.',
                ],
                notes=[
                    'Kein Akaunting-Write in V1.',
                    'Keine Konten- oder Zahlungsfinalisierung durch den Agenten.',
                ],
            )
        elif analysis.document_type.value == 'REMINDER' and review.review_status == 'READY' and not high_risks and not missing_fields:
            booking_candidate_type = 'REMINDER_REFERENCE_CHECK'
            booking_confidence = round(min(analysis.overall_confidence, 0.76), 3)
            ready_for_accounting_confirmation = False
            suggested_next_step = 'REMINDER_REFERENCE_REVIEW'
            global_decision = 'PROPOSED'
            booking_candidate = BookingCandidate(
                candidate_type=booking_candidate_type,
                counterparty_hint=counterparty.value,
                invoice_reference_hint=invoice_reference.value,
                review_focus=[
                    'Mahnung gegen bestehende Rechnung und Faelligkeit pruefen.',
                    'Kein neuer freier Buchungsvorschlag ohne vorhandenen Rechnungsbezug.',
                ],
                notes=[
                    'Kein Akaunting-Write in V1.',
                    'Mahnung bleibt ein konservativer Review-Fall.',
                ],
            )
        elif not high_risks and missing_fields:
            global_decision = 'LOW_CONFIDENCE'

        analysis_summary = (
            f'decision={global_decision};candidate={booking_candidate_type};'
            f'next={suggested_next_step};missing={",".join(missing_fields) or "-"};'
            f'confirm={ready_for_accounting_confirmation}'
        )

        return AccountingAnalysisResult(
            case_id=payload.case_id,
            accounting_review_ref=review_ref,
            booking_candidate_type=booking_candidate_type,
            supplier_or_counterparty_hint=counterparty,
            invoice_reference_hint=invoice_reference,
            amount_summary=amount_summary,
            due_date_hint=due_date_hint,
            tax_hint=tax_hint,
            booking_candidate=booking_candidate,
            booking_confidence=booking_confidence,
            accounting_risks=risks,
            missing_accounting_fields=missing_fields,
            suggested_next_step=suggested_next_step,
            global_decision=global_decision,
            ready_for_user_approval=False,
            ready_for_accounting_confirmation=ready_for_accounting_confirmation,
            analysis_summary=analysis_summary,
        )

    def _map_document_risk(self, risk: DocumentRisk) -> AccountingRisk:
        return AccountingRisk(
            code=risk.code,
            severity=risk.severity,
            message=risk.message,
            related_fields=list(risk.related_fields),
        )

    def _string_field(self, value: str | None, evidence: str | None) -> AccountingField[str]:
        if value:
            return AccountingField(value=value, status='FOUND', confidence=0.84, source_kind='CASE_CONTEXT', evidence_excerpt=evidence or value[:120])
        return AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _reference_field(self, references: list[str], extracted_refs: list[ExtractedField[str]]) -> AccountingField[str]:
        if references:
            return AccountingField(value=references[0], status='FOUND', confidence=0.84, source_kind='CASE_CONTEXT', evidence_excerpt=references[0])
        for item in extracted_refs:
            if item.status == 'FOUND' and item.value:
                return AccountingField(
                    value=item.value,
                    status='FOUND',
                    confidence=item.confidence,
                    source_kind=item.source_kind,
                    evidence_excerpt=item.evidence_excerpt,
                )
        return AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _amount_summary(self, total_amount: str | None, currency: str | None, amounts: list[DetectedAmount]) -> AmountSummary:
        total = self._decimal_field(total_amount, 'CASE_CONTEXT', total_amount)
        currency_field = AccountingField(
            value=currency,
            status='FOUND' if currency else 'MISSING',
            confidence=0.84 if currency else 0.0,
            source_kind='CASE_CONTEXT' if currency else 'NONE',
            evidence_excerpt=currency,
        )
        net = self._amount_from_detected(amounts, 'NET')
        tax = self._amount_from_detected(amounts, 'TAX')
        return AmountSummary(total_amount=total, currency=currency_field, net_amount=net, tax_amount=tax)

    def _amount_from_detected(self, amounts: list[DetectedAmount], label: str) -> AccountingField[Decimal]:
        for item in amounts:
            if item.label == label and item.amount is not None:
                return AccountingField(
                    value=item.amount,
                    status=item.status,
                    confidence=item.confidence,
                    source_kind=item.source_kind,
                    evidence_excerpt=item.evidence_excerpt,
                )
        return AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _decimal_field(self, raw_value: str | None, source_kind: str, evidence: str | None) -> AccountingField[Decimal]:
        if raw_value is None:
            return AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)
        try:
            return AccountingField(
                value=Decimal(str(raw_value)),
                status='FOUND',
                confidence=0.84,
                source_kind=source_kind,
                evidence_excerpt=evidence,
            )
        except Exception:
            return AccountingField(value=None, status='CONFLICT', confidence=0.2, source_kind='DERIVED', evidence_excerpt=evidence)

    def _date_field(self, raw_value: str | None, evidence: str | None) -> AccountingField[date]:
        if not raw_value:
            return AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)
        try:
            year, month, day = raw_value.split('-')
            return AccountingField(
                value=date(int(year), int(month), int(day)),
                status='FOUND',
                confidence=0.82,
                source_kind='CASE_CONTEXT',
                evidence_excerpt=evidence or raw_value,
            )
        except ValueError:
            return AccountingField(value=None, status='CONFLICT', confidence=0.2, source_kind='DERIVED', evidence_excerpt=raw_value)

    def _tax_hint(self, amounts: list[DetectedAmount], amount_summary: AmountSummary) -> tuple[TaxHint, list[AccountingRisk]]:
        risks: list[AccountingRisk] = []
        net = amount_summary.net_amount
        tax = amount_summary.tax_amount
        total = amount_summary.total_amount
        if net.status != 'FOUND' or tax.status != 'FOUND' or net.value is None or tax.value is None:
            # Fallback: if gross total is known, derive net+tax via standard 19% DE rate
            if total.status == 'FOUND' and total.value is not None and total.value > 0:
                derived_net = (total.value / Decimal('1.19')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                derived_tax = (total.value - derived_net).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                risks.append(AccountingRisk(
                    code='TAX_DERIVED_FROM_GROSS',
                    severity='INFO',
                    message=(
                        f'Netto/MwSt-Split nicht im Dokument gefunden — '
                        f'aus Bruttobetrag abgeleitet (19%): Netto {derived_net} €, MwSt {derived_tax} €.'
                    ),
                    related_fields=['amount_summary'],
                ))
                return TaxHint(
                    rate=AccountingField(
                        value='19%',
                        status='FOUND',
                        confidence=0.55,
                        source_kind='DERIVED',
                        evidence_excerpt=f'derived:net={derived_net},tax={derived_tax},gross={total.value}',
                    ),
                    reason='MwSt-Split nicht im Dokument erkannt — 19% Standardsatz aus Bruttobetrag abgeleitet.',
                ), risks
            return TaxHint(rate=AccountingField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None), reason='Kein belastbarer Steuerhinweis im V1-Kontext.'), risks
        if total.value is not None and net.value + tax.value != total.value:
            risks.append(
                AccountingRisk(
                    code='ACCOUNTING_AMOUNT_MISMATCH',
                    severity='HIGH',
                    message='Netto, Steuer und Gesamtbetrag sind fuer einen konservativen V1-Vorschlag nicht konsistent.',
                    related_fields=['amount_summary'],
                )
            )
            return TaxHint(rate=AccountingField(value=None, status='CONFLICT', confidence=0.2, source_kind='DERIVED', evidence_excerpt='net+tax!=total'), reason='Betragskonflikt im Steuerhinweis.'), risks

        if net.value == 0:
            risks.append(
                AccountingRisk(
                    code='ZERO_NET_AMOUNT',
                    severity='HIGH',
                    message='Netto-Betrag ist null und verhindert einen belastbaren Steuerhinweis.',
                    related_fields=['tax_hint'],
                )
            )
            return TaxHint(rate=AccountingField(value=None, status='CONFLICT', confidence=0.2, source_kind='DERIVED', evidence_excerpt='net=0'), reason='Netto-Betrag ist null.'), risks

        ratio = tax.value / net.value
        if abs(ratio - Decimal('0.19')) <= Decimal('0.01'):
            return TaxHint(
                rate=AccountingField(value='19%', status='FOUND', confidence=0.74, source_kind='DERIVED', evidence_excerpt='tax/net~19%'),
                reason='Aus Netto- und Steuerbetrag konsistent abgeleitet.',
            ), risks
        if abs(ratio - Decimal('0.07')) <= Decimal('0.01'):
            return TaxHint(
                rate=AccountingField(value='7%', status='FOUND', confidence=0.72, source_kind='DERIVED', evidence_excerpt='tax/net~7%'),
                reason='Aus Netto- und Steuerbetrag konsistent abgeleitet.',
            ), risks

        risks.append(
            AccountingRisk(
                code='UNSUPPORTED_TAX_PATTERN',
                severity='WARNING',
                message='Steuerhinweis ist nicht auf einen einfachen V1-Standardsatz abbildbar.',
                related_fields=['tax_hint'],
            )
        )
        return TaxHint(
            rate=AccountingField(value=None, status='UNCERTAIN', confidence=0.35, source_kind='DERIVED', evidence_excerpt=f'ratio={ratio}'),
            reason='Steuermuster ausserhalb des engen V1-Scope.',
        ), risks
