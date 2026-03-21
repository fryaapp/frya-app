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
Analysiere den gegebenen OCR-Text und extrahiere strukturierte Felder.

═══════════════════════════════════════
REGELN
═══════════════════════════════════════

1. Antworte AUSSCHLIESSLICH mit validem JSON. Kein Freitext. Kein Markdown.
2. Fehlende oder nicht erkennbare Felder: null. NIEMALS raten oder erfinden.
3. OCR-Text ist fehlerbehaftet. Mehrdeutiger Wert → null, confidence senken.
4. Bei mehreren Beträgen: Wähle den Gesamtbetrag (brutto). Falls unklar: null.
5. MEHRSEITIGE DOKUMENTE: Lies den GESAMTEN Text, nicht nur den Anfang.
   Bei Sammelrechnungen und mehrseitigen Rechnungen stehen Nettobetrag, MwSt-Betrag
   und Steuersatz oft auf einer SPÄTEREN Seite als der Bruttobetrag.
   Suche gezielt nach: "Zwischensumme Netto", "Nettobetrag", "Mehrwertsteuer",
   "MwSt", "Umsatzsteuer" — auch wenn diese erst auf Seite 2, 3 oder 4 erscheinen.
   Wenn Brutto auf Seite 1 steht und Netto/MwSt auf Seite 2: BEIDE extrahieren.
6. Datumsformat Ausgabe: "TT.MM.JJJJ".
7. Confidence NIE über 0.95 — OCR hat inhärente Unsicherheit.
   Alle Kernfelder klar → 0.85-0.95. Felder fehlen → 0.5-0.84.
   Nur Fragmente → 0.2-0.49. Fast nichts → 0.0-0.19.
8. Referenzen (Rechnungsnummer, Aktenzeichen, Kundennummer) sind KRITISCH für die
   Vorgangszuordnung. Extrahiere ALLE die du findest.
9. ABSENDER vs. EMPFÄNGER auf deutschen Rechnungen:
   Der ABSENDER (Rechnungssteller/Vendor/Lieferant) ist die Firma die die Rechnung AUSSTELLT:
   - Hat die USt-IDNr. / Steuernummer auf der Rechnung
   - Steht in der Fußzeile (Impressum) mit HRB, Geschäftsführer, Bankverbindung
   - Steht oft RECHTS OBEN oder im Briefkopf/Logo-Bereich
   - Hat die Gläubiger-Identifikationsnummer bei SEPA-Mandaten
   Der EMPFÄNGER (Rechnungsempfänger/Kunde) ist die Firma die die Rechnung BEKOMMT:
   - Steht im Adressfeld (oft LINKS OBEN, größer gedruckt)
   - Hat KEINE USt-IDNr. auf dieser Rechnung (außer bei Reverse Charge)
   - Steht NICHT in der Fußzeile
   REGEL: Wenn zwei Firmennamen auf der Rechnung stehen, ist die Firma mit USt-IDNr.
   und Fußzeilen-Impressum der ABSENDER ("sender"). Die Firma im Adressfeld ist
   der EMPFÄNGER ("recipient"). Extrahiere als "sender" IMMER den Rechnungssteller.

═══════════════════════════════════════
DOKUMENTTYPEN
═══════════════════════════════════════

INVOICE — Rechnung, Rechnungsnummer, Betrag, MwSt, Fälligkeitsdatum
REMINDER — Mahnung, Mahngebühr, Zahlungserinnerung
CONTRACT — Vertrag, Laufzeit, Kündigungsfrist
NOTICE — Bescheid, Finanzamt, Einspruchsfrist
TAX_DOCUMENT — Steuererklärung, Voranmeldung
RECEIPT — Quittung, Kassenbon
BANK_STATEMENT — Kontoauszug, Buchungstag
SALARY — Gehaltsabrechnung, Lohn
INSURANCE — Versicherungspolice, Beitrag
DUNNING — Inkassoschreiben, Forderungsaufstellung
CORRESPONDENCE — Brief, Mitteilung (kein klarer Typ)
OTHER — Nicht klassifizierbar

═══════════════════════════════════════
OUTPUT
═══════════════════════════════════════

{
  "document_type": "INVOICE|REMINDER|CONTRACT|NOTICE|TAX_DOCUMENT|RECEIPT|BANK_STATEMENT|SALARY|INSURANCE|DUNNING|CORRESPONDENCE|OTHER",
  "sender": "Name des Absenders oder null",
  "recipient": "Name des Empfängers oder null",
  "total_amount": Betrag als Dezimalzahl oder null,
  "net_amount": Nettobetrag oder null,
  "tax_amount": Steuerbetrag oder null,
  "tax_rate": Steuersatz (19.0, 7.0, 0.0) oder null,
  "currency": "EUR|USD|CHF|GBP oder null",
  "document_date": "TT.MM.JJJJ oder null",
  "due_date": "TT.MM.JJJJ oder null",
  "invoice_number": "Rechnungsnummer oder null",
  "customer_number": "Kundennummer oder null",
  "file_number": "Aktenzeichen oder null",
  "iban": "IBAN oder null",
  "tax_id": "Steuernummer oder USt-IdNr oder null",
  "contract_end_date": "TT.MM.JJJJ oder null",
  "cancellation_period_days": Kündigungsfrist in Tagen oder null,
  "references": ["alle gefundenen Referenznummern als Array"],
  "confidence": 0.0-0.95,
  "annotations": [
    {
      "type": "payment_note|status_note|problem_note|payment_method|correction_note|warning_note|allocation_note|tax_advisor_note|check_mark|date_note|unknown",
      "raw_text": "exakter Text wie er im OCR vorkommt",
      "interpreted": "deutsche Beschreibung was dieser Vermerk bedeutet",
      "confidence": 0.5-0.95,
      "action_suggested": "CHECK_PAYMENT_EXISTS|FLAG_PROBLEM_CASE|SUGGEST_ALLOCATION|FLAG_FOR_TAX_ADVISOR|NONE"
    }
  ]
}

═══════════════════════════════════════
HANDSCHRIFTLICHE VERMERKE UND STEMPEL
═══════════════════════════════════════

Prüfe den OCR-Text auf handschriftliche Vermerke, Stempel oder Markierungen.
Diese stehen oft am Rand, in Ecken, quer über dem Dokument, oder zwischen
gedruckten Zeilen. Sie sind oft unvollständig, abgekürzt oder schlecht lesbar.

Muster und ihre Bedeutungen:

| Muster im OCR-Text | type | action_suggested |
|---------------------|------|------------------|
| "bezahlt", "bez.", "gezahlt", "beglichen" + Datum | payment_note | CHECK_PAYMENT_EXISTS |
| "ERLEDIGT", "erled.", "DONE", "OK" | status_note | NONE |
| "Reklamation", "Beschwerde", "MÄNGEL" | problem_note | FLAG_PROBLEM_CASE |
| "per Nachnahme", "bar", "Überweisung" | payment_method | NONE |
| Durchgestrichene Beträge (wirre Zeichen über/neben Zahlen) | correction_note | NONE |
| "Achtung", "VORSICHT", "WICHTIG", "DRINGEND" | warning_note | NONE |
| "privat", "betrieblich", "50/50", "anteilig" | allocation_note | SUGGEST_ALLOCATION |
| "StB", "für Steuerberater", "Anlage" | tax_advisor_note | FLAG_FOR_TAX_ADVISOR |
| Häkchen, Kreuze (✓, ✗, X) als OCR-Artefakte | check_mark | NONE |
| Datums-Patterns ohne Kontext (3.5.25, 03/05, Mai 25) | date_note | NONE |

Wenn OCR-Text und Handschrift-Vermerk widersprüchlich sind (z.B. Betrag 49,95 EUR
aber Vermerk "45,00 bezahlt"), setze für das widersprüchliche Feld confidence -0.2
und füge es zu "missing_fields" hinzu.

Wenn kein handschriftlicher Vermerk erkennbar: "annotations": [] (leeres Array).
Erfinde KEINE Vermerke. Nur was der OCR-Text hergibt."""


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
            'CORRESPONDENCE', 'OTHER',
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
        total_raw = data.get('total_amount')
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
        inv_num = data.get('invoice_number')
        if inv_num:
            references.append(ExtractedField(
                value=str(inv_num).strip(),
                status='FOUND',
                confidence=confidence,
                source_kind='OCR_TEXT',
                evidence_excerpt=str(inv_num).strip()[:120],
            ))

        # Additional reference fields (new in prompt v2)
        for ref_val in (data.get('customer_number'), data.get('file_number')):
            if ref_val:
                references.append(ExtractedField(
                    value=str(ref_val).strip(),
                    status='FOUND',
                    confidence=confidence,
                    source_kind='OCR_TEXT',
                    evidence_excerpt=str(ref_val).strip()[:120],
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
