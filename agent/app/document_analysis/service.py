from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.document_analysis.models import (
    AnalysisDecision,
    DetectedAmount,
    DocumentAnalysisInput,
    DocumentAnalysisResult,
    DocumentRisk,
    DocumentTypeValue,
    ExtractedField,
    RecommendedNextStep,
)


_DATE_PATTERNS = (
    re.compile(r'(?P<value>\d{2}\.\d{2}\.\d{4})'),
    re.compile(r'(?P<value>\d{4}-\d{2}-\d{2})'),
)
_AMOUNT_PATTERN = re.compile(
    r'(?P<prefix>EUR|USD|CHF|GBP|€|\$)?\s*(?P<amount>\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+,\d{2}|\d+\.\d{2})\s*(?P<suffix>EUR|USD|CHF|GBP|€|\$)?',
    re.IGNORECASE,
)
_REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('invoice_number', re.compile(r'(?:rechnungsnummer|rechnung\s*nr\.?|invoice\s*number)\s*[:#-]?\s*(?P<value>[A-Z0-9\-/]+)', re.IGNORECASE)),
    ('reference', re.compile(r'(?:referenz|reference|ref\.)\s*[:#-]?\s*(?P<value>[A-Z0-9\-/]+)', re.IGNORECASE)),
    ('customer_number', re.compile(r'(?:kundennummer|customer\s*number)\s*[:#-]?\s*(?P<value>[A-Z0-9\-/]+)', re.IGNORECASE)),
    ('reminder_number', re.compile(r'(?:mahnummer|reminder\s*number)\s*[:#-]?\s*(?P<value>[A-Z0-9\-/]+)', re.IGNORECASE)),
)
_PARTY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('sender', re.compile(r'(?:absender|von|rechnung\s+von)\s*[:\-]\s*(?P<value>.+)', re.IGNORECASE)),
    ('recipient', re.compile(r'(?:empfaenger|an)\s*[:\-]\s*(?P<value>.+)', re.IGNORECASE)),
)
_AMOUNT_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('TOTAL', ('gesamt', 'gesamtbetrag', 'brutto', 'betrag faellig', 'offener betrag', 'zu zahlen', 'mahnbetrag', 'gesamt offen')),
    ('NET', ('netto',)),
    ('TAX', ('mwst', 'ust', 'umsatzsteuer', 'steuer')), 
)


class DocumentAnalysisService:
    async def analyze(self, payload: DocumentAnalysisInput) -> DocumentAnalysisResult:
        metadata = dict(payload.paperless_metadata or {})
        ocr_text = self._normalize_text(payload.ocr_text or self._metadata_text(metadata))
        preview_text = self._normalize_text(payload.preview_text or self._metadata_preview(metadata))
        case_context = dict(payload.case_context or {})
        full_text = self._merge_text(ocr_text, preview_text)
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]

        document_type = self._detect_document_type(full_text, metadata)
        sender = self._extract_party('sender', lines, metadata)
        recipient = self._extract_party('recipient', lines, metadata)
        amounts = self._extract_amounts(lines, metadata)
        currency = self._extract_currency(amounts, full_text, metadata)
        document_date = self._extract_date(lines, metadata, ('datum', 'belegdatum', 'rechnungsdatum', 'invoice date'), ('document_date', 'date', 'created_date'))
        due_date = self._extract_date(lines, metadata, ('faellig', 'zahlbar bis', 'due date', 'zahlungsziel'), ('due_date',))
        references = self._extract_references(lines, metadata)

        risks: list[DocumentRisk] = []
        warnings: list[str] = []
        missing_fields = self._missing_fields(document_type.value, sender, amounts, currency, document_date, due_date, references)

        if not ocr_text:
            risks.append(DocumentRisk(code='NO_OCR_TEXT', severity='HIGH', message='OCR-Text fehlt oder ist leer.', related_fields=['ocr_text']))
        elif len(ocr_text) < 40:
            risks.append(DocumentRisk(code='LOW_TEXT_DENSITY', severity='WARNING', message='OCR-Text ist sehr kurz.', related_fields=['ocr_text']))

        if self._has_amount_conflict(amounts):
            risks.append(DocumentRisk(code='AMOUNT_CONFLICT', severity='HIGH', message='Mehrere widerspruechliche Gesamtbetraege erkannt.', related_fields=['amounts']))

        if self._field_conflict(document_date, due_date):
            risks.append(DocumentRisk(code='DATE_CONFLICT', severity='HIGH', message='Dokumentdatum und Faelligkeit sind widerspruechlich.', related_fields=['document_date', 'due_date']))

        if missing_fields:
            severity = 'WARNING' if document_type.value in {'LETTER', 'OTHER'} else 'HIGH'
            risks.append(
                DocumentRisk(
                    code='MISSING_REQUIRED_FIELDS',
                    severity=severity,
                    message='Pflichtfelder fehlen fuer den erkannten Dokumenttyp.',
                    related_fields=missing_fields,
                )
            )

        previous_problem_types = [str(x).upper() for x in case_context.get('problem_types', []) if x]
        if 'OCR_ERROR' in previous_problem_types:
            warnings.append('Vorheriger OCR-Fehler im selben Case vorhanden.')
        if case_context.get('open_item_count', 0) > 0:
            warnings.append('Case hat bereits offene Punkte.')

        overall_confidence = self._overall_confidence(document_type, sender, recipient, amounts, currency, document_date, due_date)
        global_decision = self._decide(document_type.value, overall_confidence, risks, missing_fields, ocr_text)
        ready_for_accounting_review = self._ready_for_accounting_review(document_type.value, global_decision, missing_fields, risks)
        recommended_next_step = self._recommended_next_step(global_decision, ready_for_accounting_review, risks)

        return DocumentAnalysisResult(
            case_id=payload.case_id,
            document_ref=payload.document_ref,
            event_source=payload.event_source,
            document_type=document_type,
            sender=sender,
            recipient=recipient,
            amounts=amounts,
            currency=currency,
            document_date=document_date,
            due_date=due_date,
            references=references,
            risks=risks,
            warnings=warnings,
            missing_fields=missing_fields,
            recommended_next_step=recommended_next_step,
            global_decision=global_decision,
            ready_for_accounting_review=ready_for_accounting_review,
            overall_confidence=overall_confidence,
        )

    def _normalize_text(self, text: str | None) -> str:
        if not text:
            return ''
        normalized = str(text).replace('\r', '\n')
        normalized = re.sub(r'\n{2,}', '\n', normalized)
        return normalized.strip()

    def _merge_text(self, ocr_text: str, preview_text: str) -> str:
        if ocr_text and preview_text and preview_text not in ocr_text:
            return f'{ocr_text}\n{preview_text}'.strip()
        return ocr_text or preview_text

    def _metadata_text(self, metadata: dict) -> str:
        values: list[str] = []
        for key in ('ocr_text', 'content', 'document_text', 'text', 'notes'):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        return '\n'.join(values)

    def _metadata_preview(self, metadata: dict) -> str:
        values: list[str] = []
        for key in ('title', 'original_file_name', 'filename', 'preview', 'content_preview'):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        return '\n'.join(values)

    def _metadata_party(self, metadata: dict, keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for sub_key in ('name', 'title', 'username'):
                    sub_value = value.get(sub_key)
                    if isinstance(sub_value, str) and sub_value.strip():
                        return sub_value.strip()
        return None

    def _detect_document_type(self, text: str, metadata: dict) -> ExtractedField[DocumentTypeValue]:
        corpus = f"{text}\n{self._metadata_preview(metadata)}".lower()
        if any(token in corpus for token in ('mahnung', 'zahlungserinnerung', 'zahlungs-erinnerung', 'payment reminder')):
            return ExtractedField(value='REMINDER', status='FOUND', confidence=0.95, source_kind='OCR_TEXT', evidence_excerpt='mahnung')
        if any(token in corpus for token in ('rechnung', 'invoice')):
            return ExtractedField(value='INVOICE', status='FOUND', confidence=0.95, source_kind='OCR_TEXT', evidence_excerpt='rechnung')
        if any(token in corpus for token in ('sehr geehrte', 'mit freundlichen', 'brief', 'schreiben')):
            return ExtractedField(value='LETTER', status='FOUND', confidence=0.78, source_kind='OCR_TEXT', evidence_excerpt='brief/schreiben')
        if corpus:
            return ExtractedField(value='OTHER', status='UNCERTAIN', confidence=0.45, source_kind='OCR_TEXT', evidence_excerpt='kein klarer scope-typ erkannt')
        return ExtractedField(value='OTHER', status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt='kein Text vorhanden')

    def _extract_party(self, kind: str, lines: list[str], metadata: dict) -> ExtractedField[str]:
        if kind == 'sender':
            metadata_value = self._metadata_party(metadata, ('sender', 'correspondent', 'from', 'owner'))
        else:
            metadata_value = self._metadata_party(metadata, ('recipient', 'to', 'owner_user', 'owner'))
        if metadata_value:
            return ExtractedField(value=metadata_value, status='FOUND', confidence=0.92, source_kind='PAPERLESS_METADATA', evidence_excerpt=metadata_value[:120])

        pattern = dict(_PARTY_PATTERNS)[kind]
        for line in lines[:12]:
            match = pattern.search(line)
            if match:
                value = match.group('value').strip(' .;')
                if value:
                    return ExtractedField(value=value, status='FOUND', confidence=0.78, source_kind='OCR_TEXT', evidence_excerpt=line[:120])

        return ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _extract_amounts(self, lines: list[str], metadata: dict) -> list[DetectedAmount]:
        detected: list[DetectedAmount] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for line in lines:
            line_lower = line.lower()
            if not any(token in line_lower for token in ('eur', '€', 'usd', 'chf', 'gbp', 'betrag', 'brutto', 'netto', 'mwst', 'steuer', 'zu zahlen', 'faellig')):
                continue
            for match in _AMOUNT_PATTERN.finditer(line):
                amount_raw = match.group('amount')
                if self._looks_like_date_fragment(amount_raw, line):
                    continue
                amount = self._parse_amount(amount_raw)
                if amount is None:
                    continue
                currency = self._currency_from_match(match.group('prefix'), match.group('suffix'))
                label = self._detect_amount_label(line_lower)
                key = (label, str(amount), currency)
                if key in seen:
                    continue
                seen.add(key)
                detected.append(
                    DetectedAmount(
                        label=label,
                        amount=amount,
                        currency=currency,
                        status='FOUND',
                        confidence=0.86 if label != 'AMOUNT' else 0.68,
                        source_kind='OCR_TEXT',
                        evidence_excerpt=line[:140],
                    )
                )
        if detected:
            return detected

        metadata_amount = metadata.get('amount') or metadata.get('total')
        if metadata_amount is not None:
            parsed = self._parse_amount(str(metadata_amount))
            if parsed is not None:
                return [
                    DetectedAmount(
                        label='TOTAL',
                        amount=parsed,
                        currency=self._metadata_party(metadata, ('currency',)) or 'EUR',
                        status='FOUND',
                        confidence=0.7,
                        source_kind='PAPERLESS_METADATA',
                        evidence_excerpt=str(metadata_amount),
                    )
                ]
        return []

    def _looks_like_date_fragment(self, amount_raw: str, line: str) -> bool:
        normalized = amount_raw.strip()
        if not re.fullmatch(r'\d{1,2}\.\d{2}', normalized):
            return False
        return any(pattern.search(line) for pattern in _DATE_PATTERNS)

    def _extract_currency(self, amounts: list[DetectedAmount], text: str, metadata: dict) -> ExtractedField[str]:
        currencies = {item.currency for item in amounts if item.currency}
        if len(currencies) == 1:
            value = next(iter(currencies))
            return ExtractedField(value=value, status='FOUND', confidence=0.92, source_kind='OCR_TEXT', evidence_excerpt=value)
        if len(currencies) > 1:
            return ExtractedField(value=None, status='CONFLICT', confidence=0.2, source_kind='OCR_TEXT', evidence_excerpt=', '.join(sorted(currencies)))

        metadata_currency = self._metadata_party(metadata, ('currency',))
        if metadata_currency:
            return ExtractedField(value=metadata_currency.upper(), status='FOUND', confidence=0.7, source_kind='PAPERLESS_METADATA', evidence_excerpt=metadata_currency)

        if '€' in text or ' eur' in text.lower():
            return ExtractedField(value='EUR', status='FOUND', confidence=0.65, source_kind='OCR_TEXT', evidence_excerpt='EUR/€')
        return ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _extract_date(self, lines: list[str], metadata: dict, labels: tuple[str, ...], metadata_keys: tuple[str, ...]) -> ExtractedField[date]:
        for key in metadata_keys:
            value = metadata.get(key)
            if isinstance(value, str):
                parsed = self._parse_date(value)
                if parsed is not None:
                    return ExtractedField(value=parsed, status='FOUND', confidence=0.82, source_kind='PAPERLESS_METADATA', evidence_excerpt=value)

        matches: list[tuple[date, str]] = []
        for line in lines:
            line_lower = line.lower()
            if labels and not any(label in line_lower for label in labels):
                continue
            for pattern in _DATE_PATTERNS:
                found = pattern.search(line)
                if not found:
                    continue
                parsed = self._parse_date(found.group('value'))
                if parsed is not None:
                    matches.append((parsed, line[:140]))
        unique_dates = {value for value, _ in matches}
        if len(unique_dates) == 1 and matches:
            return ExtractedField(value=matches[0][0], status='FOUND', confidence=0.85, source_kind='OCR_TEXT', evidence_excerpt=matches[0][1])
        if len(unique_dates) > 1:
            return ExtractedField(value=None, status='CONFLICT', confidence=0.2, source_kind='OCR_TEXT', evidence_excerpt='mehrere Datumswerte erkannt')
        return ExtractedField(value=None, status='MISSING', confidence=0.0, source_kind='NONE', evidence_excerpt=None)

    def _extract_references(self, lines: list[str], metadata: dict) -> list[ExtractedField[str]]:
        refs: list[ExtractedField[str]] = []
        seen: set[str] = set()
        for line in lines:
            for _, pattern in _REFERENCE_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group('value').strip()
                if value in seen:
                    continue
                seen.add(value)
                refs.append(
                    ExtractedField(value=value, status='FOUND', confidence=0.84, source_kind='OCR_TEXT', evidence_excerpt=line[:120])
                )
        metadata_ref = metadata.get('reference') or metadata.get('archive_serial_number')
        if isinstance(metadata_ref, str) and metadata_ref.strip() and metadata_ref not in seen:
            refs.append(
                ExtractedField(
                    value=metadata_ref.strip(),
                    status='FOUND',
                    confidence=0.72,
                    source_kind='PAPERLESS_METADATA',
                    evidence_excerpt=metadata_ref.strip()[:120],
                )
            )
        return refs

    def _missing_fields(
        self,
        document_type: DocumentTypeValue | None,
        sender: ExtractedField[str],
        amounts: list[DetectedAmount],
        currency: ExtractedField[str],
        document_date: ExtractedField[date],
        due_date: ExtractedField[date],
        references: list[ExtractedField[str]],
    ) -> list[str]:
        missing: list[str] = []
        total_amount_found = any(item.label == 'TOTAL' and item.status == 'FOUND' for item in amounts) or any(item.status == 'FOUND' for item in amounts)
        reference_found = any(item.status == 'FOUND' for item in references)

        if document_type == 'INVOICE':
            if sender.status != 'FOUND':
                missing.append('sender')
            if not total_amount_found:
                missing.append('amounts')
            if currency.status != 'FOUND':
                missing.append('currency')
            if document_date.status != 'FOUND':
                missing.append('document_date')
        elif document_type == 'REMINDER':
            if sender.status != 'FOUND':
                missing.append('sender')
            if not total_amount_found:
                missing.append('amounts')
            if due_date.status != 'FOUND':
                missing.append('due_date')
            if not reference_found:
                missing.append('references')
        return missing

    def _has_amount_conflict(self, amounts: list[DetectedAmount]) -> bool:
        totals = {item.amount for item in amounts if item.label == 'TOTAL' and item.amount is not None}
        return len(totals) > 1

    def _field_conflict(self, document_date: ExtractedField[date], due_date: ExtractedField[date]) -> bool:
        if document_date.status == 'CONFLICT' or due_date.status == 'CONFLICT':
            return True
        if document_date.value and due_date.value and due_date.value < document_date.value:
            return True
        return False

    def _overall_confidence(
        self,
        document_type: ExtractedField[DocumentTypeValue],
        sender: ExtractedField[str],
        recipient: ExtractedField[str],
        amounts: list[DetectedAmount],
        currency: ExtractedField[str],
        document_date: ExtractedField[date],
        due_date: ExtractedField[date],
    ) -> float:
        values = [document_type.confidence, sender.confidence, currency.confidence, document_date.confidence]
        if recipient.status != 'MISSING':
            values.append(recipient.confidence)
        if amounts:
            values.extend([item.confidence for item in amounts])
        if due_date.status != 'MISSING':
            values.append(due_date.confidence)
        if not values:
            return 0.0
        return round(sum(values) / len(values), 3)

    def _decide(
        self,
        document_type: DocumentTypeValue | None,
        overall_confidence: float,
        risks: list[DocumentRisk],
        missing_fields: list[str],
        ocr_text: str,
    ) -> AnalysisDecision:
        risk_codes = {risk.code for risk in risks if risk.severity == 'HIGH'}
        if 'AMOUNT_CONFLICT' in risk_codes or 'DATE_CONFLICT' in risk_codes:
            return 'CONFLICT'
        if not ocr_text or 'NO_OCR_TEXT' in risk_codes:
            return 'INCOMPLETE'
        if document_type in {'INVOICE', 'REMINDER'} and missing_fields:
            return 'INCOMPLETE'
        if overall_confidence < 0.74:
            return 'LOW_CONFIDENCE'
        return 'ANALYZED'

    def _ready_for_accounting_review(
        self,
        document_type: DocumentTypeValue | None,
        decision: AnalysisDecision,
        missing_fields: list[str],
        risks: list[DocumentRisk],
    ) -> bool:
        if document_type not in {'INVOICE', 'REMINDER'}:
            return False
        if decision != 'ANALYZED':
            return False
        if missing_fields:
            return False
        return not any(risk.severity == 'HIGH' for risk in risks)

    def _recommended_next_step(
        self,
        decision: AnalysisDecision,
        ready_for_accounting_review: bool,
        risks: list[DocumentRisk],
    ) -> RecommendedNextStep:
        risk_codes = {risk.code for risk in risks}
        if 'NO_OCR_TEXT' in risk_codes:
            return 'OCR_RECHECK'
        if ready_for_accounting_review:
            return 'ACCOUNTING_REVIEW'
        if decision in {'CONFLICT', 'LOW_CONFIDENCE', 'INCOMPLETE'}:
            return 'HUMAN_REVIEW'
        return 'GENERAL_REVIEW'

    def _parse_amount(self, raw_value: str) -> Decimal | None:
        value = raw_value.replace(' ', '')
        if ',' in value:
            value = value.replace('.', '').replace(',', '.')
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None

    def _currency_from_match(self, prefix: str | None, suffix: str | None) -> str | None:
        token = (prefix or suffix or '').strip().upper()
        if token == '€':
            return 'EUR'
        if token == '$':
            return 'USD'
        return token or None

    def _detect_amount_label(self, line_lower: str) -> str:
        for label, tokens in _AMOUNT_LABELS:
            if any(token in line_lower for token in tokens):
                return label
        return 'AMOUNT'

    def _parse_date(self, raw_value: str) -> date | None:
        value = raw_value.strip()
        try:
            if '.' in value:
                day, month, year = value.split('.')
                return date(int(year), int(month), int(day))
            if '-' in value:
                year, month, day = value.split('-')
                return date(int(year), int(month), int(day))
        except ValueError:
            return None
        return None


