"""LLM-based semantic document analysis (document_analyst_semantic agent).

Uses Mistral-Small-24B via IONOS to classify documents and extract structured
fields from OCR text. Replaces the regex-based DocumentAnalysisService when an
API key is configured for the 'document_analyst_semantic' agent.

OCR note: OCR itself runs upstream (Tika/Paperless) — this service receives
already-extracted text. The 'document_analyst' config (LightOn OCR-2-1B) is
reserved for future direct LLM-OCR; current MVP uses Tika + this semantic layer.

Fallback: if the LLM call fails for any reason, DocumentAnalysisService
(regex-based) is used automatically.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from litellm import acompletion

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))
_OWN_COMPANY_NAME: str | None = os.environ.get('FRYA_OWN_COMPANY_NAME') or None

from app.document_analysis.models import (
    AnalysisDecision,
    Annotation,
    AnnotationAction,
    AnnotationType,
    DetectedAmount,
    DocumentAnalysisInput,
    DocumentAnalysisResult,
    DocumentTypeValue,
    DocumentRisk,
    ExtractedField,
)
from app.document_analysis.service import DocumentAnalysisService

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du bist ein Dokumentenanalyse-Experte für deutschsprachige Geschäftsdokumente.
Dein Output ist AUSSCHLIESSLICH ein einzelnes JSON-Objekt. Sonst nichts.

═══════════════════════════════════════
OUTPUT-FORMAT (IMMER DIESES FORMAT)
═══════════════════════════════════════

{
  "document_type": "INVOICE|REMINDER|CONTRACT|NOTICE|TAX_DOCUMENT|RECEIPT|BANK_STATEMENT|PAYSLIP|INSURANCE|OFFER|CREDIT_NOTE|DELIVERY_NOTE|LETTER|PRIVATE|AGB|WIDERRUF|OTHER",
  "sender": "Firma oder Person die das Dokument erstellt hat oder null",
  "recipient": "Firma oder Person an die es adressiert ist oder null",
  "gross_amount": Bruttobetrag als Zahl oder null,
  "net_amount": Nettobetrag oder null,
  "tax_amount": MwSt-Betrag oder null,
  "tax_rate": 19 oder 7 oder 0 oder null,
  "currency": "EUR",
  "document_date": "TT.MM.JJJJ" oder null,
  "due_date": "TT.MM.JJJJ" oder null,
  "document_number": "Rechnungsnummer oder Aktenzeichen oder null",
  "iban": "IBAN oder null",
  "ust_id": "USt-IDNr. des Absenders oder null",
  "payment_reference": "Verwendungszweck oder null",
  "contract_end_date": "TT.MM.JJJJ" oder null,
  "cancellation_period_days": Zahl oder null,
  "dunning_level": 1-4 oder null,
  "references": ["alle Referenznummern"],
  "has_attachments": true oder false,
  "is_business_relevant": true oder false,
  "private_info": "Extrahierte Termine/Infos bei privaten Dokumenten oder null",
  "confidence": 0.0-0.95,
  "missing_fields": ["felder die fehlen"],
  "annotations": []
}

═══════════════════════════════════════
REGELN FÜR GUTEN OUTPUT
═══════════════════════════════════════

1. Jedes Feld das du im Text findest: ausfüllen. Jedes Feld das du NICHT findest: null setzen.

2. Suche im GESAMTEN Text — Netto, MwSt und Steuersatz stehen oft auf Seite 2, 3 oder 4.
   Suchwörter: "Zwischensumme Netto", "Nettobetrag", "Mehrwertsteuer", "MwSt", "Umsatzsteuer".

3. Confidence-Skala:
   - 0.85-0.95 = Alle Kernfelder klar gefunden
   - 0.50-0.84 = Einige Felder fehlen oder sind unsicher
   - 0.20-0.49 = Nur Fragmente erkennbar
   - 0.00-0.19 = Fast nichts erkennbar
   Höchstwert: 0.95 (OCR hat immer eine Rest-Unsicherheit).

4. ABSENDER erkennen — so findest du ihn:
   Die Firma mit USt-IDNr. oder Steuernummer = ABSENDER
   Die Firma in der Fußzeile (HRB, Geschäftsführer, Bankverbindung) = ABSENDER
   Die Firma im Logo/Briefkopf rechts oben = ABSENDER
   Die Firma im Adressfeld links oben = EMPFÄNGER
   Beispiel: "1&1 Telecom GmbH" hat USt-IDNr. DE813789825 in der Fußzeile → sender = "1&1 Telecom GmbH"
   Beispiel: "Fino Versand GbR" steht im Adressfeld → recipient = "Fino Versand GbR"

5. Firmennamen vollständig übernehmen wie im Impressum: "1&1 Telecom GmbH" statt "1&1" oder "1und1".

6. Datumsformat: Immer "TT.MM.JJJJ" ausgeben (z.B. "15.03.2026").

═══════════════════════════════════════
DOKUMENTTYP ERKENNEN
═══════════════════════════════════════

Erkenne den Typ anhand dieser Schlüsselwörter:

| Typ | Schlüsselwörter im Text |
|-----|------------------------|
| INVOICE | "Rechnung", "Rechnungsnummer", "Invoice", Betrag + Fälligkeitsdatum |
| REMINDER | "Mahnung", "Zahlungserinnerung", "Mahngebühr", Mahnungsstufe |
| CONTRACT | "Vertrag", "Laufzeit", "Kündigungsfrist", "Vertragslaufzeit" |
| NOTICE | "Bescheid", "Finanzamt", "Einspruchsfrist", "Amt", "Behörde" |
| TAX_DOCUMENT | "Steuererklärung", "Voranmeldung", "Umsatzsteuer-Voranmeldung" |
| RECEIPT | "Quittung", "Kassenbon", "Barzahlung" |
| BANK_STATEMENT | "Kontoauszug", "Buchungstag", "Saldo", "Kontobewegungen" |
| PAYSLIP | "Lohnabrechnung", "Gehaltsabrechnung", "Bruttolohn", "Sozialversicherung" |
| INSURANCE | "Versicherungspolice", "Versicherungsschein", "Beitrag", "Deckung" |
| OFFER | "Angebot", "Kostenvoranschlag", "gültig bis", "unverbindlich" |
| CREDIT_NOTE | "Gutschrift", "Stornorechnung", "Rechnungskorrektur" |
| DELIVERY_NOTE | "Lieferschein", "Wareneingang", "Lieferung" |
| LETTER | Geschäftlicher Brief ohne Betrag |
| PRIVATE | Privater Brief, Einladung, Kita-Brief, kein Geschäftsbezug, kein Betrag |
| AGB | "Allgemeine Geschäftsbedingungen", "AGB" (als eigenständiges Dokument) |
| WIDERRUF | "Widerrufsbelehrung", "Widerrufsrecht" |
| OTHER | Keines der obigen Muster passt |

═══════════════════════════════════════
MULTI-DOKUMENT-PDFs
═══════════════════════════════════════

Manche PDFs enthalten eine Rechnung + AGB + Widerrufsbelehrung zusammen.
Analysiere nur das HAUPTDOKUMENT (die Rechnung).
Setze has_attachments = true wenn du AGB, Widerrufsbelehrung oder Datenschutzhinweise als Nebendokument erkennst.

═══════════════════════════════════════
PRIVATE DOKUMENTE
═══════════════════════════════════════

Wenn das Dokument privat ist (kein Geschäftsbezug, kein Vendor, kein Betrag):
- document_type = "PRIVATE"
- is_business_relevant = false
- Extrahiere trotzdem: sender, document_date, und nützliche Infos in private_info
- Beispiel Kita-Brief: private_info = "Kinderfest Samstag 15.03.2026, 15:00 Uhr"

═══════════════════════════════════════
HANDSCHRIFTLICHE VERMERKE
═══════════════════════════════════════

Suche nach handschriftlichen Vermerken oder Stempeln im OCR-Text:

| Muster | type | action_suggested |
|--------|------|------------------|
| "bezahlt", "bez.", "gezahlt" + Datum | payment_note | CHECK_PAYMENT_EXISTS |
| "ERLEDIGT", "OK", "erled." | status_note | NONE |
| "Reklamation", "Beschwerde", "MÄNGEL" | problem_note | FLAG_PROBLEM_CASE |
| "bar", "Überweisung", "per Nachnahme" | payment_method | NONE |
| "privat", "betrieblich", "50/50" | allocation_note | SUGGEST_ALLOCATION |
| "StB", "für Steuerberater" | tax_advisor_note | FLAG_FOR_TAX_ADVISOR |

Nur Vermerke die tatsächlich im OCR-Text stehen. Wenn keine → annotations = [].

═══════════════════════════════════════
BEISPIELE
═══════════════════════════════════════

Beispiel 1 — Vollständige Rechnung:
Input enthält: "Rechnungsnummer: 151122582904", "Bruttobetrag: 8,54 EUR", "MwSt 19%: 1,36 EUR", "Netto: 7,18 EUR", Fußzeile mit "1&1 Telecom GmbH, USt-ID DE813789825"
→ {"document_type": "INVOICE", "sender": "1&1 Telecom GmbH", "gross_amount": 8.54, "net_amount": 7.18, "tax_amount": 1.36, "tax_rate": 19, "document_number": "151122582904", "ust_id": "DE813789825", "confidence": 0.92, ...}

Beispiel 2 — Unvollständiges Dokument:
Input enthält: "Rechnung" aber keinen Betrag, keinen Absender
→ {"document_type": "INVOICE", "sender": null, "gross_amount": null, "confidence": 0.35, "missing_fields": ["sender", "gross_amount", "document_number"], ...}

Beispiel 3 — Privater Brief:
Input enthält: "Liebe Eltern, Kinderfest am Samstag 15.03.2026 um 15 Uhr", "Kita Sonnenschein"
→ {"document_type": "PRIVATE", "sender": "Kita Sonnenschein", "is_business_relevant": false, "private_info": "Kinderfest Samstag 15.03.2026, 15:00 Uhr", "confidence": 0.85, ...}\
"""


class DocumentAnalystSemanticService:
    """Semantic document analysis via LLM (document_analyst_semantic agent).

    Drop-in replacement for DocumentAnalysisService.analyze() with automatic
    fallback to regex-based analysis on any LLM error.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None,
        base_url: str | None,
        *,
        fallback_service: DocumentAnalysisService | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._fallback = fallback_service or DocumentAnalysisService()

    async def analyze(self, payload: DocumentAnalysisInput) -> DocumentAnalysisResult:
        """Run semantic LLM analysis; fall back to regex on any error."""
        try:
            return await self._analyze_with_llm(payload)
        except Exception as exc:
            logger.warning(
                'document_analyst_semantic LLM call failed — using regex fallback: %s', exc
            )
            return await self._fallback.analyze(payload)

    async def _analyze_with_llm(self, payload: DocumentAnalysisInput) -> DocumentAnalysisResult:
        ocr_text = (payload.ocr_text or '').strip()
        if not ocr_text:
            # No OCR text — delegate to regex service
            return await self._fallback.analyze(payload)

        # ── Prompt-injection guard ────────────────────────────────────────────
        from app.security.input_sanitizer import sanitize_ocr_text
        _inj = sanitize_ocr_text(ocr_text)
        if _inj.is_blocked:
            logger.warning(
                'document_analyst: prompt injection BLOCKED in OCR text '
                '(risk=%.2f, patterns=%s) case=%s',
                _inj.risk_score, _inj.detected_patterns, payload.case_id,
            )
            result = await self._fallback.analyze(payload)
            return result.model_copy(update={
                'risks': result.risks + [DocumentRisk(
                    code='PROMPT_INJECTION_BLOCKED',
                    severity='HIGH',
                    message=(
                        f'Prompt-Injection im OCR-Text erkannt (Risk-Score: {_inj.risk_score:.2f}). '
                        f'Muster: {", ".join(_inj.detected_patterns)}. '
                        'LLM-Aufruf abgebrochen, Regex-Fallback verwendet.'
                    ),
                    related_fields=['ocr_text'],
                )],
                'overall_confidence': 0.0,
            })
        if _inj.injection_detected:
            logger.warning(
                'document_analyst: injection suspected (risk=%.2f) — '
                'proceeding with cleaned text, case=%s',
                _inj.risk_score, payload.case_id,
            )
        effective_ocr = _inj.cleaned_text

        metadata = dict(payload.paperless_metadata or {})
        truncated = effective_ocr[:16000]
        user_content = f'Dokumenttext:\n{truncated}'
        if metadata.get('title'):
            user_content = f'Titel: {metadata["title"]}\n\n{user_content}'
        if _OWN_COMPANY_NAME:
            user_content = (
                f'Hinweis: Der aktuelle Nutzer/Tenant ist "{_OWN_COMPANY_NAME}". '
                f'Wenn dieser Name im Dokument vorkommt, ist er der EMPFÄNGER, nicht der Absender.\n\n'
                + user_content
            )

        call_kwargs: dict = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
            'max_tokens': 1024,
            'temperature': 0.0,
            'timeout': _LLM_TIMEOUT,
        }
        if self._api_key:
            call_kwargs['api_key'] = self._api_key
        if self._base_url:
            call_kwargs['api_base'] = self._base_url

        completion = await acompletion(**call_kwargs)
        raw = (completion.choices[0].message.content or '').strip()
        result = self._parse_llm_response(raw, payload)

        # ── Extraction validation (hallucination detection) ───────────────────
        from app.security.output_validator import validate_extraction
        _extraction = {
            'sender': result.sender.value if result.sender else None,
            'total_amount': result.amounts[0].amount if result.amounts else None,
            'invoice_number': result.references[0].value if result.references else None,
        }
        _val = validate_extraction(effective_ocr, _extraction)
        if _val.findings:
            _severity_map = {'HIGH': 'HIGH', 'MEDIUM': 'WARNING', 'LOW': 'INFO'}
            _extra_risks = [
                DocumentRisk(
                    code='HALLUCINATION_SUSPECTED',
                    severity=_severity_map.get(f.severity, 'WARNING'),
                    message=f'Extrahierter Wert nicht im Quelltext gefunden: {f.detail}',
                    related_fields=[f.field],
                )
                for f in _val.findings
            ]
            _new_confidence = min(
                result.overall_confidence,
                0.5 if _val.overall_severity == 'HIGH' else 0.7,
            )
            result = result.model_copy(update={
                'risks': result.risks + _extra_risks,
                'overall_confidence': _new_confidence,
            })

        return result

    def _parse_llm_response(
        self, raw: str, payload: DocumentAnalysisInput
    ) -> DocumentAnalysisResult:
        """Parse LLM JSON response into DocumentAnalysisResult.

        Raises on invalid JSON or unexpected structure — caller falls back to regex.
        """
        text = raw.strip()
        # Strip markdown code fences if model wraps its output
        if text.startswith('```'):
            lines = text.split('\n')
            text = '\n'.join(lines[1:])
            if text.endswith('```'):
                text = text[:-3].strip()

        data: dict = json.loads(text)  # raises ValueError/JSONDecodeError on bad JSON

        raw_type = str(data.get('document_type') or 'OTHER').upper()
        _valid_types = {
            'INVOICE', 'REMINDER', 'LETTER', 'CONTRACT', 'NOTICE', 'TAX_DOCUMENT',
            'RECEIPT', 'BANK_STATEMENT', 'SALARY', 'INSURANCE', 'DUNNING',
            'CORRESPONDENCE', 'PAYSLIP', 'OFFER', 'CREDIT_NOTE', 'DELIVERY_NOTE',
            'PRIVATE', 'AGB', 'WIDERRUF', 'OTHER',
        }
        if raw_type not in _valid_types:
            raw_type = 'OTHER'
        doc_type: DocumentTypeValue = raw_type  # type: ignore[assignment]

        confidence = min(1.0, max(0.0, float(data.get('confidence') or 0.7)))

        document_type = ExtractedField(
            value=doc_type,
            status='FOUND' if doc_type != 'OTHER' else 'UNCERTAIN',
            confidence=confidence,
            source_kind='OCR_TEXT',
            evidence_excerpt=doc_type,
        )

        sender_val = data.get('sender')
        sender = ExtractedField(
            value=str(sender_val).strip() if sender_val else None,
            status='FOUND' if sender_val else 'MISSING',
            confidence=confidence if sender_val else 0.0,
            source_kind='OCR_TEXT',
        )

        recipient_val = data.get('recipient')
        recipient = ExtractedField(
            value=str(recipient_val).strip() if recipient_val else None,
            status='FOUND' if recipient_val else 'MISSING',
            confidence=confidence if recipient_val else 0.0,
            source_kind='OCR_TEXT',
        )

        currency_raw = (data.get('currency') or '').strip().upper() or None
        amounts: list[DetectedAmount] = []
        total_raw = data.get('gross_amount') or data.get('total_amount')
        if total_raw is not None:
            try:
                total_decimal = Decimal(str(total_raw))
                amounts.append(DetectedAmount(
                    label='TOTAL',
                    amount=total_decimal,
                    currency=currency_raw or 'EUR',
                    status='FOUND',
                    confidence=confidence,
                    source_kind='OCR_TEXT',
                ))
            except (InvalidOperation, ValueError):
                pass

        currency = ExtractedField(
            value=currency_raw or ('EUR' if amounts else None),
            status='FOUND' if (currency_raw or amounts) else 'MISSING',
            confidence=confidence if (currency_raw or amounts) else 0.0,
            source_kind='OCR_TEXT',
        )

        document_date = ExtractedField(
            value=_parse_date(data.get('document_date')),
            status='FOUND' if _parse_date(data.get('document_date')) else 'MISSING',
            confidence=confidence if _parse_date(data.get('document_date')) else 0.0,
            source_kind='OCR_TEXT',
        )

        due_date = ExtractedField(
            value=_parse_date(data.get('due_date')),
            status='FOUND' if _parse_date(data.get('due_date')) else 'MISSING',
            confidence=confidence if _parse_date(data.get('due_date')) else 0.0,
            source_kind='OCR_TEXT',
        )

        references = []
        inv_num = data.get('document_number') or data.get('invoice_number')
        if inv_num:
            references.append(ExtractedField(
                value=str(inv_num).strip(),
                status='FOUND',
                confidence=confidence,
                source_kind='OCR_TEXT',
                evidence_excerpt=str(inv_num).strip()[:120],
                label='document_number',
            ))

        # Additional reference fields
        for ref_key in ('customer_number', 'file_number', 'payment_reference'):
            ref_val = data.get(ref_key)
            if ref_val:
                references.append(ExtractedField(
                    value=str(ref_val).strip(),
                    status='FOUND',
                    confidence=confidence,
                    source_kind='OCR_TEXT',
                    evidence_excerpt=str(ref_val).strip()[:120],
                    label=ref_key,
                ))

        # USt-ID (new field name: ust_id, fallback: tax_id)
        ust_id = data.get('ust_id') or data.get('tax_id')
        if ust_id:
            references.append(ExtractedField(
                value=str(ust_id).strip(),
                status='FOUND',
                confidence=confidence,
                source_kind='OCR_TEXT',
                evidence_excerpt=str(ust_id).strip()[:120],
                label='ust_id',
            ))

        # references[] array — CRITICAL for CaseEngine 4-layer assignment
        for ref in (data.get('references') or []):
            if ref and str(ref).strip():
                ref_str = str(ref).strip()
                if not any(r.value == ref_str for r in references):
                    references.append(ExtractedField(
                        value=ref_str,
                        status='FOUND',
                        confidence=confidence,
                        source_kind='OCR_TEXT',
                        evidence_excerpt=ref_str[:120],
                    ))

        # net_amount and tax_amount as additional DetectedAmount entries
        for label, key in (('NET', 'net_amount'), ('TAX', 'tax_amount')):
            raw_val = data.get(key)
            if raw_val is not None:
                try:
                    amounts.append(DetectedAmount(
                        label=label,
                        amount=Decimal(str(raw_val)),
                        currency=currency_raw or 'EUR',
                        status='FOUND',
                        confidence=confidence,
                        source_kind='OCR_TEXT',
                    ))
                except (InvalidOperation, ValueError):
                    pass

        # ── Parse handwritten annotations (Der Kopf — Vermerke) ─────────────────
        annotations: list[Annotation] = []
        _valid_types: set[str] = {
            'payment_note', 'status_note', 'problem_note', 'payment_method',
            'correction_note', 'warning_note', 'allocation_note', 'tax_advisor_note',
            'check_mark', 'date_note', 'unknown',
        }
        _valid_actions: set[str] = {
            'CHECK_PAYMENT_EXISTS', 'FLAG_PROBLEM_CASE', 'SUGGEST_ALLOCATION',
            'FLAG_FOR_TAX_ADVISOR', 'NONE',
        }
        for _ann in (data.get('annotations') or []):
            if not isinstance(_ann, dict):
                continue
            _atype = str(_ann.get('type') or 'unknown').lower()
            if _atype not in _valid_types:
                _atype = 'unknown'
            _action = str(_ann.get('action_suggested') or 'NONE').upper()
            if _action not in _valid_actions:
                _action = 'NONE'
            _ann_conf = min(1.0, max(0.0, float(_ann.get('confidence') or 0.5)))
            annotations.append(Annotation(
                type=_atype,  # type: ignore[arg-type]
                raw_text=str(_ann.get('raw_text') or ''),
                interpreted=str(_ann.get('interpreted') or ''),
                confidence=_ann_conf,
                action_suggested=_action,  # type: ignore[arg-type]
            ))

        # ── New fields from prompt v3 ─────────────────────────────────────────
        has_attachments = bool(data.get('has_attachments', False))
        is_business_relevant = bool(data.get('is_business_relevant', True))
        private_info_raw = data.get('private_info')
        private_info = str(private_info_raw).strip() if private_info_raw else None

        # Reuse the regex service's risk/decision logic
        svc = self._fallback
        missing_fields = svc._missing_fields(
            doc_type, sender, amounts, currency, document_date, due_date, references
        )
        risks: list[DocumentRisk] = []
        if not (payload.ocr_text or '').strip():
            risks.append(DocumentRisk(
                code='NO_OCR_TEXT', severity='HIGH',
                message='OCR-Text fehlt oder ist leer.', related_fields=['ocr_text'],
            ))
        if missing_fields:
            severity = 'WARNING' if doc_type in {'LETTER', 'OTHER'} else 'HIGH'
            risks.append(DocumentRisk(
                code='MISSING_REQUIRED_FIELDS', severity=severity,
                message='Pflichtfelder fehlen fuer den erkannten Dokumenttyp.',
                related_fields=missing_fields,
            ))

        global_decision = svc._decide(
            doc_type, confidence, risks, missing_fields, payload.ocr_text or ''
        )
        ready = svc._ready_for_accounting_review(doc_type, global_decision, missing_fields, risks)
        next_step = svc._recommended_next_step(global_decision, ready, risks)

        return DocumentAnalysisResult(
            analysis_version='document-analyst-semantic-v1',
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
            annotations=annotations,
            warnings=[],
            missing_fields=missing_fields,
            recommended_next_step=next_step,
            global_decision=global_decision,
            ready_for_accounting_review=ready,
            overall_confidence=confidence,
            has_attachments=has_attachments,
            is_business_relevant=is_business_relevant,
            private_info=private_info,
        )


def _parse_date(raw: object) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if '.' in s:
            d, m, y = s.split('.')
            return date(int(y), int(m), int(d))
        if '-' in s:
            y, m, d = s.split('-')
            return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        pass
    return None
