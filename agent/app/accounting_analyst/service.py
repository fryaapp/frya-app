"""LLM-based accounting analyst — generates SKR03 booking proposals.

Uses Mistral-Small-24B via IONOS (accounting_analyst agent config).
Falls back to rule-based proposal if no API key is configured or LLM fails.
All proposals are PROPOSE_ONLY — never auto-executed.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from litellm import acompletion

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

from app.accounting_analyst.schemas import (
    BookingProposal,
    CaseAnalysisInput,
    SKR03_COMMON_ACCOUNTS,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du bist ein deutschsprachiger Buchhalter mit Expertise im SKR03-Kontenrahmen.
Dein Output ist ausschließlich ein einzelnes JSON-Objekt.

═══════════════════════════════════════
OUTPUT-FORMAT (IMMER DIESES FORMAT)
═══════════════════════════════════════

{
  "skr03_soll": "Kontonummer Soll (z.B. 3300)",
  "skr03_soll_name": "Kontobezeichnung Soll",
  "skr03_haben": "Kontonummer Haben (z.B. 1600)",
  "skr03_haben_name": "Kontobezeichnung Haben",
  "tax_rate": Steuersatz als Zahl (19.0, 7.0, 0.0) oder null,
  "tax_amount": Steuerbetrag oder null,
  "net_amount": Nettobetrag oder null,
  "gross_amount": Bruttobetrag oder null,
  "reasoning": "Begründung mit Referenz auf Beleg, Kreditor, Historie",
  "confidence": 0.0-0.90
}

═══════════════════════════════════════
REGELN
═══════════════════════════════════════

1. Jedes Feld das du im Beleg findest: ausfüllen. Jedes Feld das du im Beleg NICHT findest: null.

2. Den Steuersatz aus dem Beleg übernehmen.
   "steuerfrei" oder "0% MwSt" → tax_rate = 0.0.
   Wenn im Beleg kein Steuersatz steht → tax_rate = null und confidence um 0.15 senken.

3. Brutto = Netto + Steuer prüfen. Wenn die Rechnung nicht aufgeht:
   Alle Werte aus dem Beleg übernehmen und den Widerspruch im reasoning benennen.
   Die Werte bleiben wie im Beleg — du korrigierst sie nicht.

4. Höchstwert für confidence: 0.90.
   - Wiederkehrender Kreditor + klare Zuordnung → 0.80-0.90
   - Erstmaliger Kreditor aber klares Bild → 0.65-0.79
   - Mehrere mögliche Konten → 0.40-0.64
   - Unsichere Zuordnung → unter 0.40

5. Wenn es einen früheren Buchungsvorschlag für denselben Beleg gibt: im reasoning referenzieren.

6. Ausgangsrechnungen: Soll = 1400 (Forderungen), Haben = 7000 (Umsatzerlöse 19%).
   Eingangsrechnungen: Soll = Aufwandskonto, Haben = 1600 (Verbindlichkeiten).

═══════════════════════════════════════
SKR03-KONTEN (häufig)
═══════════════════════════════════════

Aktiva/Passiva: 1000 Kasse | 1200 Bank | 1400 Forderungen LuL | 1571 VSt 7% | 1576 VSt 19% | 1600 Verbindlichkeiten LuL
Aufwand: 3300 Wareneingang 19% | 3400 Wareneingang 7% | 3801 Eingangsleistungen (nicht steuerbar) | 3806 Eingangsleistungen EU | 4200 Raumkosten | 4300 Versicherungen | 4910 Porto | 4920 Telefon | 4940 Kfz | 4950 Software/IT | 4955 Internet/Hosting | 4980 Buchführung
Erlöse: 7000 Umsatzerlöse 19% | 7010 Umsatzerlöse 7%

═══════════════════════════════════════
BEISPIELE
═══════════════════════════════════════

Beispiel 1 — Telefonrechnung:
Input: Vorgangstyp=incoming_invoice, Lieferant=1&1 Telecom GmbH, Gesamtbetrag=8.54 EUR
→ {"skr03_soll": "4920", "skr03_soll_name": "Telefon", "skr03_haben": "1600", "skr03_haben_name": "Verbindlichkeiten LuL", "tax_rate": 19.0, "tax_amount": 1.36, "net_amount": 7.18, "gross_amount": 8.54, "reasoning": "1&1 Telecom ist wiederkehrender Telefonanbieter. Konto 4920 Telefon, 19% MwSt aus Beleg.", "confidence": 0.88}

Beispiel 2 — Serverkosten:
Input: Vorgangstyp=incoming_invoice, Lieferant=Hetzner Online GmbH, Gesamtbetrag=6.38 EUR
→ {"skr03_soll": "4955", "skr03_soll_name": "Internet/Hosting", "skr03_haben": "1600", "skr03_haben_name": "Verbindlichkeiten LuL", "tax_rate": 19.0, "tax_amount": 1.02, "net_amount": 5.36, "gross_amount": 6.38, "reasoning": "Hetzner ist Hosting-Anbieter. Konto 4955 Internet/Hosting.", "confidence": 0.87}

Beispiel 3 — Unbekannter Kreditor, kein Steuersatz:
Input: Vorgangstyp=incoming_invoice, Lieferant=XYZ Services Ltd., Gesamtbetrag=500.00 EUR
→ {"skr03_soll": "3300", "skr03_soll_name": "Wareneingang 19%", "skr03_haben": "1600", "skr03_haben_name": "Verbindlichkeiten LuL", "tax_rate": null, "tax_amount": null, "net_amount": null, "gross_amount": 500.00, "reasoning": "Erstmaliger Kreditor, Steuersatz im Beleg nicht erkennbar. Vorläufig Konto 3300, Steuersatz muss geprüft werden.", "confidence": 0.45}
""" + '\n'.join(f'  {k}: {v}' for k, v in SKR03_COMMON_ACCOUNTS.items())


class AccountingAnalystService:
    """LLM-based SKR03 booking proposal generator.

    Falls back to rule-based analysis when no API key is available or LLM fails.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    async def analyze(self, case_data: CaseAnalysisInput) -> BookingProposal:
        """Generate a booking proposal; fall back to rule-based on any error."""
        if self._api_key:
            try:
                proposal = await self._analyze_with_llm(case_data)
            except Exception as exc:
                logger.warning(
                    'accounting_analyst LLM call failed — using rule-based fallback: %s', exc
                )
                proposal = _rule_based_proposal(case_data)
        else:
            proposal = _rule_based_proposal(case_data)

        # ── Booking proposal validation ───────────────────────────────────────
        from app.security.output_validator import validate_booking_proposal
        _val = validate_booking_proposal(proposal)
        if _val.findings:
            logger.warning(
                'accounting_analyst: proposal validation findings for case %s: %s',
                proposal.case_id,
                [f'{f.field}={f.issue}' for f in _val.findings],
            )
            if _val.overall_severity == 'HIGH':
                new_confidence = min(proposal.confidence, 0.4)
            elif _val.overall_severity == 'MEDIUM':
                new_confidence = min(proposal.confidence, 0.6)
            else:
                new_confidence = proposal.confidence
            proposal = proposal.model_copy(update={'confidence': new_confidence})

        return proposal

    async def _analyze_with_llm(self, case_data: CaseAnalysisInput) -> BookingProposal:
        user_content = _build_user_message(case_data)

        call_kwargs: dict = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
            'max_tokens': 512,
            'temperature': 0.0,
            'timeout': _LLM_TIMEOUT,
        }
        if self._api_key:
            call_kwargs['api_key'] = self._api_key
        if self._base_url:
            call_kwargs['api_base'] = self._base_url

        completion = await acompletion(**call_kwargs)
        raw = (completion.choices[0].message.content or '').strip()
        return _parse_llm_response(raw, case_data)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_accounting_analyst_service(
    repo: object | None,
    config: dict | None,
) -> AccountingAnalystService:
    """Build service from LLMConfigRepository config dict.

    Returns a no-key service (rule-based fallback) when repo/config/key is absent.
    """
    model_str = ''
    api_key: str | None = None
    base_url: str | None = None

    if repo is not None and config is not None:
        model_str = (config.get('model') or '').strip()
        base_url = config.get('base_url') or None
        if model_str:
            try:
                api_key = repo.decrypt_key_for_call(config)  # type: ignore[union-attr]
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
            return AccountingAnalystService(model=full_model, api_key=api_key, base_url=base_url)

    # Fallback — rule-based only
    return AccountingAnalystService(model='', api_key=None, base_url=None)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

def _parse_llm_response(raw: str, case_data: CaseAnalysisInput) -> BookingProposal:
    text = raw.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:])
        if text.endswith('```'):
            text = text[:-3].strip()

    data: dict = json.loads(text)

    confidence = min(1.0, max(0.0, float(data.get('confidence') or 0.7)))

    gross = _to_decimal(data.get('gross_amount')) or case_data.total_amount
    net = _to_decimal(data.get('net_amount'))
    tax = _to_decimal(data.get('tax_amount'))
    tax_rate_raw = data.get('tax_rate')
    tax_rate = float(tax_rate_raw) if tax_rate_raw is not None else None

    return BookingProposal(
        case_id=case_data.case_id,
        skr03_soll=str(data['skr03_soll']).strip() if data.get('skr03_soll') else None,
        skr03_soll_name=str(data['skr03_soll_name']).strip() if data.get('skr03_soll_name') else None,
        skr03_haben=str(data['skr03_haben']).strip() if data.get('skr03_haben') else None,
        skr03_haben_name=str(data['skr03_haben_name']).strip() if data.get('skr03_haben_name') else None,
        tax_rate=tax_rate,
        tax_amount=tax,
        net_amount=net,
        gross_amount=gross,
        reasoning=str(data.get('reasoning') or '').strip() or None,
        confidence=confidence,
        analyst_version='accounting-analyst-v1',
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

def _rule_based_proposal(case_data: CaseAnalysisInput) -> BookingProposal:
    case_type = case_data.case_type
    gross = case_data.total_amount or Decimal('0')

    if case_type == 'incoming_invoice':
        soll, soll_name = '3300', 'Wareneingang 19 % MwSt'
        haben, haben_name = '1600', 'Verbindlichkeiten aus Lieferungen und Leistungen'
        tax_rate = 19.0
    elif case_type == 'outgoing_invoice':
        soll, soll_name = '1400', 'Forderungen aus Lieferungen und Leistungen'
        haben, haben_name = '7000', 'Umsatzerloese 19 % MwSt'
        tax_rate = 19.0
    elif case_type in ('receipt', 'bank_statement'):
        soll, soll_name = '4980', 'Buchfuehrungskosten'
        haben, haben_name = '1200', 'Bank'
        tax_rate = 19.0
    else:
        soll, soll_name = '3300', 'Wareneingang 19 % MwSt'
        haben, haben_name = '1600', 'Verbindlichkeiten aus Lieferungen und Leistungen'
        tax_rate = 19.0

    if gross:
        divisor = Decimal(str(1 + tax_rate / 100))
        net = (gross / divisor).quantize(Decimal('0.01'))
        tax_amount = (gross - net).quantize(Decimal('0.01'))
    else:
        net = Decimal('0.00')
        tax_amount = Decimal('0.00')

    return BookingProposal(
        case_id=case_data.case_id,
        skr03_soll=soll,
        skr03_soll_name=soll_name,
        skr03_haben=haben,
        skr03_haben_name=haben_name,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        net_amount=net,
        gross_amount=gross or None,
        reasoning='Regelbasierter Vorschlag (kein LLM konfiguriert).',
        confidence=0.5,
        analyst_version='accounting-analyst-v1',
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_decimal(val: object) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return None


def _build_user_message(case_data: CaseAnalysisInput) -> str:
    lines = [f'Vorgangstyp: {case_data.case_type}']
    if case_data.vendor_name:
        lines.append(f'Lieferant/Absender: {case_data.vendor_name}')
    if case_data.total_amount:
        lines.append(f'Gesamtbetrag: {case_data.total_amount} {case_data.currency}')
    if case_data.due_date:
        lines.append(f'Faelligkeitsdatum: {case_data.due_date}')
    if case_data.title:
        lines.append(f'Titel: {case_data.title}')
    if case_data.document_type:
        lines.append(f'Dokumenttyp (aus Dokumentenanalyse): {case_data.document_type}')
    return '\n'.join(lines)
