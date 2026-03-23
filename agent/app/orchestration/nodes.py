from __future__ import annotations

import json
import logging
import os
import uuid

from litellm import acompletion

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))

_logger = logging.getLogger(__name__)

from app.accounting_analysis.models import AccountingAnalysisInput, AccountingAnalysisResult
from app.accounting_review.models import AccountingReviewDraft
from app.dependencies import (
    get_accounting_analysis_service,
    get_akaunting_connector,
    get_approval_service,
    get_audit_service,
    get_case_repository,
    get_document_analysis_service,
    get_open_items_service,
    get_paperless_connector,
    get_policy_access_layer,
    get_problem_case_service,
    get_telegram_case_link_repository,
    get_telegram_connector,
)
from app.document_analysis.models import DocumentAnalysisInput, DocumentAnalysisResult
from app.open_items.models import OpenItemStatus
from app.orchestration.state import AgentState


_ACTIVE_ITEM_STATUSES: set[OpenItemStatus] = {'OPEN', 'WAITING_USER', 'WAITING_DATA', 'SCHEDULED', 'PENDING_APPROVAL'}


async def classify_intent(state: AgentState) -> AgentState:
    if state.get('document_ref') or state.get('paperless_metadata') or state.get('source') == 'paperless_webhook':
        state['intent'] = 'DOCUMENT_REVIEW'
        return state

    text = (state.get('message') or '').lower()
    if 'rechnung' in text or 'dokument' in text:
        intent = 'DOCUMENT_REVIEW'
    elif 'buch' in text or 'konto' in text:
        intent = 'ACCOUNTING_QUERY'
    elif 'workflow' in text or 'wiedervorlage' in text:
        intent = 'WORKFLOW_TRIGGER'
    else:
        intent = 'UNKNOWN'
    state['intent'] = intent
    return state


async def draft_action_with_llm(state: AgentState) -> AgentState:
    prompt = """\
Du bist der Orchestrator von FRYA — einem KI-gestützten Buchhaltungs- und DMS-System für deutsche KMU, Freelancer und Privathaushalte.

Deine Aufgabe: Analysiere die Nutzeranfrage oder den Systemvorgang und erzeuge einen strukturierten Aktionsplan als JSON.

Deine Rolle ist Planung und Delegation. Die Ausführung übernehmen andere Agenten.

═══════════════════════════════════════
KONTEXT
═══════════════════════════════════════

Du erhältst:
- [SYSTEMKONTEXT]: Aktuelle Cases, Open Items, Audit-Historie aus PostgreSQL
- [NACHRICHT]: Die Nutzeranfrage oder der Systemtrigger
- [MEMORY]: Langzeitgedächtnis mit Nutzerpräferenzen und gelernten Mustern

Quellen der Wahrheit:
- Akaunting = finanzielle Wahrheit (Buchungen, Konten, Rechnungen)
- Paperless = Dokumentwahrheit (Originale, OCR-Rohtext, Archiv)
- CaseEngine (PostgreSQL) = Vorgangswahrheit (Cases, Timeline, Open Items, Audit)

═══════════════════════════════════════
OUTPUT-FORMAT (IMMER DIESES FORMAT)
═══════════════════════════════════════

Dein Output ist ausschließlich ein einzelnes JSON-Objekt:

{
  "action": "AKTION_KEY",
  "target_agent": "accounting_analyst | document_analyst | deadline_analyst | risk_consistency | communicator | memory_curator | none",
  "parameters": {
    "beschreibung": "Was genau getan werden soll",
    "case_id": "UUID oder null",
    "document_ref": "Paperless-ID oder null",
    "priority": "CRITICAL | HIGH | NORMAL | LOW"
  },
  "reasoning": "Warum diese Aktion, in einem Satz",
  "confidence": 0.0-0.85,
  "reversible": true oder false,
  "approval_hint": "AUTO | PROPOSE_ONLY | REQUIRE_USER_APPROVAL | BLOCK_ESCALATE"
}

Gültige action-Werte:
  document_type_detect, tags_set, correspondent_assign, ocr_reanalyze,
  akaunting_bill_invoice_draft_create, booking_proposal_create, booking_finalize,
  payment_proposal_create, payment_execute, document_mark_done, open_item_create,
  reminder_send, problem_case_create, human_readable_review_generate,
  recurring_document_draft_create, correction_case_mark, side_effect_run_start,
  rule_policy_edit, invoice_create, offer_create, reminder_personal,
  NONE

═══════════════════════════════════════
APPROVAL-LOGIK
═══════════════════════════════════════

Du schlägst einen approval_hint vor. Das System entscheidet final über die Approval Matrix.
- AUTO: Risikoarme, reversible Aktionen (Tags, Open Items, Dokumenttyp)
- PROPOSE_ONLY: Buchungsvorschläge, Entwürfe, Erinnerungen
- REQUIRE_USER_APPROVAL: Buchung finalisieren, Workflows starten, Regeln ändern
- BLOCK_ESCALATE: Zahlungen ausführen → IMMER BLOCK
Im Zweifel: den höheren Modus wählen.

═══════════════════════════════════════
PRIORISIERUNG
═══════════════════════════════════════

CRITICAL — Fristablauf ≤48h, Zahlungsrückläufer, Compliance-Verstoß, Einspruchsfrist
HIGH — Fristablauf ≤7 Tage, offene Diskrepanz, Operator-Anfrage
NORMAL — Standard-Verarbeitung, reguläre Vorschläge
LOW — Statistik, Memory-Verdichtung, nicht-dringende Meldungen

═══════════════════════════════════════
HARTE REGELN
═══════════════════════════════════════

1. action=payment_execute hat IMMER reversible=false. Zahlungen sind irreversibel.
   approval_hint für payment_execute ist IMMER BLOCK_ESCALATE.

2. Höchstwert für confidence: 0.85 bei LLM-basierten Zuordnungen.

3. Jedes Feld in parameters stammt aus dem Kontext ([SYSTEMKONTEXT], [NACHRICHT], [MEMORY]).
   Fehlende Information → confidence senken und im reasoning benennen.

4. API-Keys, Tokens und System-Pfade gehören ausschließlich in die Konfiguration, nicht in parameters.

5. Zahlungswünsche in natürlicher Sprache ("Bezahl die Rechnung") immer als
   action=payment_proposal_create behandeln. Die Freigabe erfolgt separat.

6. Case-Status PAID/CLOSED wird ausschließlich durch den Operator oder das Approval-System gesetzt.

7. Es gibt nur Statusänderungen, keine Löschaktionen. Alle Daten bleiben erhalten.

8. Bei Widersprüchen zwischen Quellen: action=problem_case_create.

9. Ausgangsrechnungen: "Erstell eine Rechnung für X" → action=invoice_create, target_agent=accounting_analyst.
   Angebote: "Erstell ein Angebot für X" → action=offer_create, target_agent=accounting_analyst.

10. Private Erinnerungen: "Erinnere mich an X" → action=reminder_personal, target_agent=communicator.

═══════════════════════════════════════
CASE-ZUORDNUNG (VORGANGSERKENNUNG)
═══════════════════════════════════════

Die CaseEngine ordnet Dokumente automatisch zu:
1. Hard Reference Match (Rechnungsnummer, Aktenzeichen) → CERTAIN
2. Entity + Amount + Date Match → HIGH
3. Cluster-Heuristik (Gläubiger + Betrag + Zeitfenster) → MEDIUM
4. LLM-Inferenz → maximal MEDIUM

Die CaseEngine-Zuordnung ist verbindlich. Bei CaseConflict (AMBIGUOUS_ASSIGNMENT, DUPLICATE_CASE_SUSPECT): Eskalation an Operator via Communicator.

═══════════════════════════════════════
BEISPIELE
═══════════════════════════════════════

Beispiel 1 — Neue Rechnung analysieren:
Input: Neues Dokument von Paperless (document_ref: 42)
→ {"action": "document_type_detect", "target_agent": "document_analyst", "parameters": {"beschreibung": "Neues Dokument analysieren", "document_ref": "42", "priority": "NORMAL"}, "confidence": 0.80, "reversible": true, "approval_hint": "AUTO"}

Beispiel 2 — Zahlung gewünscht:
Input: "Bezahl die Rechnung von 1&1"
→ {"action": "payment_proposal_create", "target_agent": "accounting_analyst", "parameters": {"beschreibung": "Zahlungsvorschlag für 1&1 Rechnung erstellen", "priority": "NORMAL"}, "confidence": 0.75, "reversible": true, "approval_hint": "PROPOSE_ONLY"}

Beispiel 3 — Widerspruch erkannt:
Input: Betrag im Dokument 100€, im Case 95€
→ {"action": "problem_case_create", "target_agent": "none", "parameters": {"beschreibung": "Betragskonflikt: Dokument 100€ vs. Case 95€", "priority": "HIGH"}, "confidence": 0.70, "reversible": true, "approval_hint": "AUTO"}\
"""
    messages = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': state.get('message', '')},
    ]

    # Load LLM config from repository (DB first, then ENV fallback)
    _repo = None
    llm_config = None
    try:
        from app.dependencies import get_llm_config_repository as _get_repo
        _repo = _get_repo()
        llm_config = await _repo.get_config_or_fallback('orchestrator')
    except Exception:
        pass

    model_str = (llm_config.get('model') or '').strip() if llm_config else ''

    if not model_str:
        state['planned_action'] = {'action': 'NONE', 'reason': 'No LLM model configured', 'reversible': True}
        state.setdefault('approved', False)
        return state

    provider = (llm_config.get('provider') or '').strip() if llm_config else ''
    # IONOS AI Hub uses OpenAI-compatible API — map to openai/ prefix for litellm
    litellm_provider = 'openai' if provider == 'ionos' else provider
    if provider == 'ionos':
        full_model = f'openai/{model_str}'
    elif litellm_provider and '/' not in model_str:
        full_model = f'{litellm_provider}/{model_str}'
    else:
        full_model = model_str

    try:
        api_key = _repo.decrypt_key_for_call(llm_config) if _repo and llm_config else None
        base_url = (llm_config.get('base_url') or None) if llm_config else None

        call_kwargs: dict = {
            'model': full_model,
            'messages': messages,
            'max_tokens': 300,
            'timeout': _LLM_TIMEOUT,
        }
        if api_key:
            call_kwargs['api_key'] = api_key
        if base_url:
            call_kwargs['api_base'] = base_url

        completion = await acompletion(**call_kwargs)
        content = completion.choices[0].message.content
        parsed = {'raw': content, 'action': 'NONE'}
        try:
            parsed_candidate = json.loads(content)
            if isinstance(parsed_candidate, dict):
                parsed = parsed_candidate
        except Exception:
            pass
        state['planned_action'] = parsed

        # ── Log orchestrator decision to audit trail ───────────────────────
        await get_audit_service().log_event({
            'event_id': 'orch-' + uuid.uuid4().hex[:12],
            'case_id': state.get('case_id', 'unknown'),
            'source': state.get('source', 'api'),
            'agent_name': 'frya-orchestrator',
            'approval_status': 'NOT_REQUIRED',
            'action': 'ORCHESTRATOR_PLAN',
            'result': parsed.get('action', 'NONE'),
            'llm_model': full_model,
            'llm_input': {'message': state.get('message', '')},
            'llm_output': {
                'raw_response': content,
                'parsed_action': parsed,
                'model_used': full_model,
                'confidence': parsed.get('confidence'),
                'reasoning': parsed.get('reasoning'),
                'approval_hint': parsed.get('approval_hint'),
            },
        })
    except Exception as exc:
        state['planned_action'] = {'action': 'NONE', 'reason': f'LLM unavailable: {exc}', 'reversible': True}

    state.setdefault('approved', False)
    return state


async def _build_document_context(case_id: str) -> dict[str, object]:
    audit_service = get_audit_service()
    open_items_service = get_open_items_service()
    problem_service = get_problem_case_service()

    chronology = await audit_service.by_case(case_id, limit=25)
    open_items = await open_items_service.list_by_case(case_id)
    problems = await problem_service.by_case(case_id, limit=10)

    return {
        'recent_actions': [event.action for event in chronology[-10:]],
        'open_item_count': len(open_items),
        'open_item_titles': [item.title for item in open_items[:5]],
        'problem_titles': [problem.title for problem in problems[:5]],
        'problem_types': [problem.exception_type for problem in problems if problem.exception_type],
    }


def _document_policy_refs() -> list[dict[str, str]]:
    policy_access = get_policy_access_layer()
    return policy_access.get_policy_refs(
        [
            'orchestrator_policy',
            'runtime_policy',
            'compliance_policy',
            'problemfall_policy',
            'document_analyst_policy',
            'output_schemas',
        ]
    )


def _accounting_policy_refs() -> list[dict[str, str]]:
    policy_access = get_policy_access_layer()
    return policy_access.get_policy_refs(
        [
            'orchestrator_policy',
            'runtime_policy',
            'compliance_policy',
            'accounting_analyst_policy',
            'output_schemas',
        ]
    )


def _merge_policy_refs(*collections: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for items in collections:
        for item in items:
            key = (item.get('policy_name'), item.get('policy_version'), item.get('policy_path'))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


async def run_document_analyst(state: AgentState) -> AgentState:
    # ── E-Rechnung fast path (before any LLM call) ────────────────────────────
    # If raw PDF or XML bytes are present and contain a ZUGFeRD / XRechnung
    # e-invoice, parse the structured XML directly.  Machine-readable XML is
    # ground truth — confidence 1.0, no LLM needed.
    _pdf_bytes: bytes | None = state.get('pdf_bytes')  # type: ignore[assignment]
    if _pdf_bytes:
        try:
            from app.e_invoice.parser import (
                detect_e_invoice,
                e_invoice_to_document_analysis_result,
                parse_xrechnung,
                parse_zugferd,
            )
            _e_type = detect_e_invoice(_pdf_bytes)
            if _e_type is not None:
                _e_data = parse_zugferd(_pdf_bytes) if _pdf_bytes[:4] == b'%PDF' else parse_xrechnung(_pdf_bytes)
                _e_result = e_invoice_to_document_analysis_result(
                    _e_data,
                    case_id=state.get('case_id', 'uncategorized'),
                    document_ref=state.get('document_ref'),
                    event_source=state.get('source', 'e_invoice'),
                )
                state['document_analysis'] = _e_result.model_dump(mode='json')
                return state
        except Exception:
            pass  # Fall through to normal OCR/LLM analysis on parse failure

    # Load both document analyst configs (DB first, then ENV fallback).
    # document_analyst          = LightOnOCR-2-1B — Stage 1: visual OCR from PDF images
    # document_analyst_semantic = Mistral-Small-24B — Stage 2: field classification from text
    _da_repo = None
    _da_config = None
    _semantic_config = None
    try:
        from app.dependencies import get_llm_config_repository as _get_repo
        _da_repo = _get_repo()
        _da_config = await _da_repo.get_config_or_fallback('document_analyst')
        _semantic_config = await _da_repo.get_config_or_fallback('document_analyst_semantic')
        state['document_analyst_model'] = (_da_config.get('model') or '').strip() or None
    except Exception:
        state['document_analyst_model'] = None

    # Choose analysis service:
    # - Semantic path: document_analyst_semantic has a decryptable API key → LLM analysis
    # - Regex path: fallback when semantic config is unavailable or missing key
    analysis_service = _build_document_analysis_service(_da_repo, _semantic_config)

    metadata = dict(state.get('paperless_metadata') or {})
    document_ref = str(state.get('document_ref') or metadata.get('document_id') or metadata.get('id') or '') or None
    fetch_warning = None

    if document_ref:
        try:
            remote_document = await get_paperless_connector().get_document(document_ref)
            if isinstance(remote_document, dict):
                merged_metadata = dict(remote_document)
                merged_metadata.update(metadata)
                metadata = merged_metadata
        except Exception as exc:
            fetch_warning = str(exc)

    # ── Stage 1: LightOnOCR — PDF visual OCR when no usable text available ────
    # Runs when ocr_text is absent or below the minimum useful length.
    # Pipeline: PDF bytes → page images → LightOnOCR-2-1B → plain text
    # That text is then passed to Stage 2 (Mistral semantic) below.
    from app.document_analysis.ocr_service import MIN_OCR_CHARS, read_pdf_from_local_path, run_lightocr
    _ocr_text: str | None = state.get('ocr_text')
    if not _ocr_text or len(_ocr_text.strip()) < MIN_OCR_CHARS:
        _pdf_bytes: bytes | None = None

        # Try 1: local stored file (Telegram-sourced documents)
        _stored_path = (
            metadata.get('stored_relative_path')
            or (state.get('paperless_metadata') or {}).get('stored_relative_path')
        )
        if _stored_path:
            _pdf_bytes = read_pdf_from_local_path(_stored_path)

        # Try 2: download from Paperless (numeric doc ID)
        if _pdf_bytes is None and document_ref and document_ref.isdigit():
            try:
                _pdf_bytes = await get_paperless_connector().download_document_bytes(document_ref)
            except Exception as _dl_exc:
                _logger.debug('Paperless PDF download failed for %s: %s', document_ref, _dl_exc)

        # Run LightOnOCR if we have PDF bytes and an API key
        if _pdf_bytes and _da_config and _da_repo:
            _ocr_model = (_da_config.get('model') or '').strip()
            _ocr_api_key = _da_repo.decrypt_key_for_call(_da_config)
            _ocr_base_url = _da_config.get('base_url')
            if _ocr_model and _ocr_api_key:
                try:
                    _ocr_text = await run_lightocr(
                        _pdf_bytes,
                        model=f'openai/{_ocr_model}',
                        api_key=_ocr_api_key,
                        base_url=_ocr_base_url,
                        max_pages=3,
                    )
                    state['ocr_text'] = _ocr_text
                    _logger.info(
                        'LightOnOCR stage 1 completed: %d chars for case %s',
                        len(_ocr_text), state.get('case_id'),
                    )
                except Exception as _ocr_exc:
                    _logger.warning(
                        'LightOnOCR stage 1 failed for case %s: %s',
                        state.get('case_id'), _ocr_exc,
                    )

    case_context = await _build_document_context(state.get('case_id', 'uncategorized'))
    if fetch_warning:
        case_context['fetch_warning'] = fetch_warning

    analysis_input = DocumentAnalysisInput(
        case_id=state.get('case_id', 'uncategorized'),
        document_ref=document_ref,
        event_source=state.get('source', 'api'),
        paperless_metadata=metadata,
        ocr_text=state.get('ocr_text'),
        preview_text=state.get('preview_text'),
        case_context=case_context,
    )
    analysis = await analysis_service.analyze(analysis_input)
    state['document_ref'] = document_ref
    state['paperless_metadata'] = metadata
    state['case_context'] = case_context
    state['document_analysis'] = analysis.model_dump(mode='json')
    return state


def _build_document_analysis_service(
    repo: object,
    semantic_config: dict | None,
) -> object:
    """Return DocumentAnalystSemanticService if the semantic config has a usable API key,
    otherwise return the regex-based DocumentAnalysisService fallback."""
    if repo is None or not semantic_config:
        return get_document_analysis_service()

    model_str = (semantic_config.get('model') or '').strip()
    if not model_str:
        return get_document_analysis_service()

    try:
        api_key = repo.decrypt_key_for_call(semantic_config)  # type: ignore[union-attr]
    except Exception:
        api_key = None

    if not api_key:
        return get_document_analysis_service()

    from app.document_analysis.semantic_service import DocumentAnalystSemanticService

    provider = (semantic_config.get('provider') or '').strip()
    if provider == 'ionos':
        full_model = f'openai/{model_str}'
    elif provider and '/' not in model_str:
        full_model = f'{provider}/{model_str}'
    else:
        full_model = model_str

    base_url = semantic_config.get('base_url') or None
    return DocumentAnalystSemanticService(
        model=full_model,
        api_key=api_key,
        base_url=base_url,
    )


async def _ensure_case_open_item(
    case_id: str,
    *,
    title: str,
    description: str,
    source: str,
    desired_status: OpenItemStatus,
    document_ref: str | None = None,
    accounting_ref: str | None = None,
) -> str | None:
    open_items_service = get_open_items_service()
    existing = await open_items_service.list_by_case(case_id)
    for item in existing:
        if item.title == title and item.status in _ACTIVE_ITEM_STATUSES:
            if item.status != desired_status:
                await open_items_service.update_status(item.item_id, desired_status)
            return item.item_id

    created = await open_items_service.create_item(
        case_id=case_id,
        title=title,
        description=description,
        source=source,
        document_ref=document_ref,
        accounting_ref=accounting_ref,
    )
    if desired_status != 'OPEN':
        await open_items_service.update_status(created.item_id, desired_status)
    return created.item_id


async def _transition_case_open_items(
    case_id: str,
    *,
    source: str,
    titles: set[str],
    final_status: OpenItemStatus,
) -> None:
    open_items_service = get_open_items_service()
    existing = await open_items_service.list_by_case(case_id)
    for item in existing:
        if item.source != source:
            continue
        if item.title not in titles:
            continue
        if item.status not in _ACTIVE_ITEM_STATUSES:
            continue
        await open_items_service.update_status(item.item_id, final_status)


async def _ensure_problem_case(case_id: str, *, title: str, details: str, document_ref: str | None = None) -> str | None:
    problem_service = get_problem_case_service()
    existing = await problem_service.by_case(case_id, limit=50)
    for item in existing:
        if item.title == title:
            return item.problem_id

    created = await problem_service.add_case(
        case_id=case_id,
        title=title,
        details=details,
        severity='HIGH',
        exception_type='DOCUMENT_ANALYSIS_CONFLICT',
        document_ref=document_ref,
        created_by='document-analyst',
    )
    return created.problem_id


def _document_result_summary(result: DocumentAnalysisResult) -> str:
    return (
        f'decision={result.global_decision};type={result.document_type.value or "OTHER"};'
        f'next={result.recommended_next_step};missing={",".join(result.missing_fields) or "-"};'
        f'ready={result.ready_for_accounting_review}'
    )


def _build_accounting_review_draft(result: DocumentAnalysisResult) -> AccountingReviewDraft | None:
    if result.document_type.value not in {'INVOICE', 'REMINDER'}:
        return None
    if result.global_decision != 'ANALYZED':
        return None
    if not result.ready_for_accounting_review:
        return None
    if result.missing_fields:
        return None

    total_amount = next((item for item in result.amounts if item.label == 'TOTAL' and item.status == 'FOUND'), None)
    if total_amount is None:
        total_amount = next((item for item in result.amounts if item.status == 'FOUND'), None)
    if total_amount is None or result.currency.status != 'FOUND' or result.document_date.status != 'FOUND':
        return None
    if result.sender.status != 'FOUND':
        return None
    if result.document_type.value == 'REMINDER':
        if result.due_date.status != 'FOUND':
            return None
        if not any(ref.status == 'FOUND' for ref in result.references):
            return None

    references = [ref.value for ref in result.references if ref.status == 'FOUND' and ref.value]
    risk_codes = [risk.code for risk in result.risks]
    focus = [
        'Betrag und Waehrung gegen Originaldokument pruefen.',
        'Dokumentdatum und Referenzen vor manueller Folgearbeit bestaetigen.',
    ]
    if result.document_type.value == 'REMINDER':
        focus.insert(0, 'Mahnbezug, Faelligkeit und offene Referenzrechnung pruefen.')
    else:
        focus.insert(0, 'Rechnungsdaten und Kernfelder fuer die Review Queue bestaetigen.')

    return AccountingReviewDraft(
        case_id=result.case_id,
        document_ref=result.document_ref,
        source_document_type=result.document_type.value,
        review_status='READY',
        ready_for_accounting_review=True,
        analysis_summary=_document_result_summary(result),
        sender=result.sender.value,
        recipient=result.recipient.value,
        total_amount=str(total_amount.amount) if total_amount.amount is not None else None,
        currency=result.currency.value,
        document_date=result.document_date.value.isoformat() if result.document_date.value else None,
        due_date=result.due_date.value.isoformat() if result.due_date.value else None,
        references=references,
        missing_fields=list(result.missing_fields),
        risks=risk_codes,
        suggested_review_focus=focus,
        next_step='ACCOUNTING_REVIEW',
    )


def _accounting_review_ref(review: AccountingReviewDraft) -> str:
    return f'{review.case_id}:{review.document_ref or "none"}:{review.review_version}'


def _accounting_analysis_open_item_title(result: AccountingAnalysisResult) -> str:
    if result.booking_candidate_type == 'REMINDER_REFERENCE_CHECK':
        return 'Mahnungsbezug pruefen'
    return 'Buchungsvorschlag pruefen'


_DOCUMENT_TYPE_MAP: dict[str, str] = {
    'INVOICE': 'Eingangsrechnung',
    'REMINDER': 'Mahnung',
    'CONTRACT': 'Vertrag',
    'NOTICE': 'Bescheid',
    'TAX_DOCUMENT': 'Steuerdokument',
    'RECEIPT': 'Quittung',
    'BANK_STATEMENT': 'Kontoauszug',
    'PAYSLIP': 'Lohnabrechnung',
    'INSURANCE': 'Versicherung',
    'OFFER': 'Angebot',
    'CREDIT_NOTE': 'Gutschrift',
    'DELIVERY_NOTE': 'Lieferschein',
    'LETTER': 'Brief',
    'PRIVATE': 'Privat',
    'AGB': 'AGB',
    'WIDERRUF': 'Sonstiges',
    'OTHER': 'Sonstiges',
}


async def _writeback_to_paperless(
    *,
    document_ref: str,
    analysis: DocumentAnalysisResult,
    case_id: str,
) -> None:
    """Enrich a Paperless document with analysis metadata.

    Sets correspondent, document type, tags, title, and custom fields.
    Never raises — errors are logged and swallowed by the caller.
    """
    connector = get_paperless_connector()
    doc_id = int(document_ref)
    patch_data: dict = {}

    # ── Correspondent ──────────────────────────────────────────────────────
    vendor = analysis.sender.value if analysis.sender.status == 'FOUND' else None
    if vendor:
        corr_id = await connector.find_or_create_correspondent(vendor)
        if corr_id is not None:
            patch_data['correspondent'] = corr_id

    # ── Document Type ──────────────────────────────────────────────────────
    if analysis.document_type.status in ('FOUND', 'UNCERTAIN'):
        dt_name = _DOCUMENT_TYPE_MAP.get(analysis.document_type.value, 'Sonstiges')
        dt_id = await connector.find_or_create_document_type(dt_name)
        if dt_id is not None:
            patch_data['document_type'] = dt_id

    # ── Tags (merge with existing — never overwrite, deduplicate) ────────
    existing_doc = await connector.get_document(document_ref)
    tag_ids: set[int] = set(existing_doc.get('tags', []))
    analysiert_id = await connector.find_or_create_tag('frya:analysiert', '#2196F3')
    if analysiert_id is not None:
        tag_ids.add(analysiert_id)
    # Add vorsteuer-relevant for invoices
    if analysis.document_type.status in ('FOUND', 'UNCERTAIN') and analysis.document_type.value == 'INVOICE':
        vst_id = await connector.find_or_create_tag('vorsteuer-relevant', '#673AB7')
        if vst_id is not None:
            tag_ids.add(vst_id)
    if tag_ids:
        patch_data['tags'] = sorted(tag_ids)

    # ── Title: "Vendor — Betrag€ — Datum" ─────────────────────────────────
    title_parts: list[str] = []
    if vendor:
        title_parts.append(vendor)
    total = next(
        (a.amount for a in analysis.amounts if a.label == 'TOTAL' and a.status == 'FOUND'),
        None,
    )
    currency = analysis.currency.value if analysis.currency.status == 'FOUND' else 'EUR'
    if total is not None:
        title_parts.append(f'{total:.2f}{currency}')
    if analysis.document_date.status == 'FOUND' and analysis.document_date.value:
        title_parts.append(analysis.document_date.value.strftime('%b %Y'))
    if title_parts:
        patch_data['title'] = ' — '.join(title_parts)

    # ── Custom Fields ──────────────────────────────────────────────────────
    field_ids = await connector.get_custom_field_ids()
    custom_fields: list[dict] = []

    if 'frya_case_id' in field_ids:
        custom_fields.append({'field': field_ids['frya_case_id'], 'value': case_id})
    if 'frya_status' in field_ids:
        custom_fields.append({'field': field_ids['frya_status'], 'value': 'analysiert'})
    if 'confidence' in field_ids:
        custom_fields.append({'field': field_ids['confidence'], 'value': str(analysis.overall_confidence)})
    if total is not None and 'betrag_brutto' in field_ids:
        custom_fields.append({'field': field_ids['betrag_brutto'], 'value': str(total)})
    # Extract invoice number from references
    inv_ref = next(
        (r.value for r in analysis.references if r.status == 'FOUND' and r.label in ('invoice_number', 'Rechnungsnummer')),
        None,
    )
    if inv_ref and 'rechnungsnummer' in field_ids:
        custom_fields.append({'field': field_ids['rechnungsnummer'], 'value': inv_ref})

    if custom_fields:
        patch_data['custom_fields'] = custom_fields

    if patch_data:
        await connector.update_document_metadata(doc_id, patch_data)
        _logger.info('Paperless writeback OK for doc %s: %s', document_ref, list(patch_data.keys()))


async def finalize_document_review(state: AgentState) -> AgentState:
    result = DocumentAnalysisResult.model_validate(state.get('document_analysis', {}))
    case_id = state.get('case_id', 'uncategorized')
    document_ref = result.document_ref
    summary = _document_result_summary(result)
    policy_refs = _document_policy_refs()
    accounting_review = _build_accounting_review_draft(result)

    await get_audit_service().log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': case_id,
            'source': state.get('source', 'api'),
            'document_ref': document_ref,
            'agent_name': 'document-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': 'DOCUMENT_ANALYSIS_COMPLETED',
            'result': summary,
            'llm_output': result.model_dump(mode='json'),
            'policy_refs': policy_refs,
        }
    )

    # ── Annotation action handling (handwritten notes from Der Kopf) ──────────
    for _ann in result.annotations:
        if _ann.action_suggested == 'CHECK_PAYMENT_EXISTS':
            # Check Akaunting for existing payment matching vendor + amount
            _payment_found = False
            try:
                _vendor_hint = result.sender.value if result.sender.status == 'FOUND' else None
                _total_hint = next(
                    (a.amount for a in result.amounts if a.label == 'TOTAL' and a.status == 'FOUND'),
                    None,
                )
                if _vendor_hint or _total_hint:
                    _txs = await get_akaunting_connector().search_transactions(
                        contact_name=_vendor_hint,
                        amount=float(_total_hint) if _total_hint is not None else None,
                    )
                    _payment_found = bool(_txs)
            except Exception as _ak_exc:
                _logger.debug('CHECK_PAYMENT_EXISTS Akaunting lookup failed: %s', _ak_exc)

            _description = (
                f'Handschriftlicher Zahlungsvermerk erkannt: "{_ann.raw_text}"\n'
                f'Interpretation: {_ann.interpreted}\n'
            )
            if _payment_found:
                _description += 'Zahlungseingang in Akaunting gefunden — Beleg möglicherweise bereits gebucht.'
            else:
                _description += 'Bitte pruefen ob Zahlungseingang in der Buchhaltung erfasst ist.'

            await _ensure_case_open_item(
                case_id,
                title='Zahlungsvermerk pruefen',
                description=_description,
                source='document_analyst_annotation',
                desired_status='OPEN',
                document_ref=document_ref,
            )
        elif _ann.action_suggested == 'FLAG_PROBLEM_CASE':
            await _ensure_problem_case(
                case_id,
                title='Problemvermerk erkannt',
                details=(
                    f'Handschriftlicher Problemvermerk: "{_ann.raw_text}"\n'
                    f'Interpretation: {_ann.interpreted}'
                ),
                document_ref=document_ref,
            )
        elif _ann.action_suggested == 'SUGGEST_ALLOCATION':
            await _ensure_case_open_item(
                case_id,
                title='Kostenaufteilung pruefen',
                description=(
                    f'Zuordnungshinweis erkannt: "{_ann.raw_text}"\n'
                    f'Interpretation: {_ann.interpreted}\n'
                    f'Moegliche Aufteilung privat/betrieblich pruefen.'
                ),
                source='document_analyst_annotation',
                desired_status='OPEN',
                document_ref=document_ref,
            )
        elif _ann.action_suggested == 'FLAG_FOR_TAX_ADVISOR':
            # Tag document in Paperless as "steuerberater"
            if document_ref and document_ref.isdigit():
                try:
                    await get_paperless_connector().add_tag(document_ref, 'steuerberater')
                except Exception as _tag_exc:
                    _logger.warning('Could not add steuerberater tag to doc %s: %s', document_ref, _tag_exc)
            await get_audit_service().log_event({
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': state.get('source', 'api'),
                'document_ref': document_ref,
                'agent_name': 'document-analyst',
                'approval_status': 'NOT_REQUIRED',
                'action': 'TAX_ADVISOR_FLAG_SET',
                'result': f'Steuerberater-Vermerk: {_ann.interpreted}',
                'llm_output': _ann.model_dump(mode='json'),
            })

    # ── CaseEngine integration ─────────────────────────────────────────────────
    _tenant_raw = state.get('tenant_id') or (state.get('paperless_metadata') or {}).get('tenant_id')
    if _tenant_raw:
        try:
            _tenant_uuid = uuid.UUID(str(_tenant_raw))
        except (ValueError, AttributeError):
            _tenant_uuid = None
        if _tenant_uuid is not None:
            _logger.info('CaseEngine: tenant_id resolved: %s', _tenant_uuid)
            from app.case_engine.doc_analyst_integration import integrate_document_analysis
            _meta = state.get('paperless_metadata') or {}
            _vendor = result.sender.value if result.sender.status == 'FOUND' else None
            _total = next(
                (a.amount for a in result.amounts if a.label == 'TOTAL' and a.status == 'FOUND'),
                None,
            )
            _currency = result.currency.value if result.currency.status == 'FOUND' else None
            _doc_date = result.document_date.value if result.document_date.status == 'FOUND' else None
            _due_date = result.due_date.value if result.due_date.status == 'FOUND' else None
            _refs = [
                (r.label or 'invoice_number', r.value)
                for r in result.references
                if r.status == 'FOUND' and r.value
            ]
            _filename = _meta.get('filename') or _meta.get('original_file_name')
            _doc_type = result.document_type.value if result.document_type.status in ('FOUND', 'UNCERTAIN') else None
            state['case_engine_result'] = await integrate_document_analysis(
                tenant_id=_tenant_uuid,
                event_source=result.event_source,
                document_ref=document_ref,
                document_type_value=_doc_type,
                vendor_name=_vendor,
                total_amount=_total,
                currency=_currency,
                document_date=_doc_date,
                due_date=_due_date,
                reference_values=_refs,
                filename=_filename,
                overall_confidence=result.overall_confidence,
                orchestration_case_id=case_id,
                line_items=[
                    {'description': li.description, 'quantity': li.quantity,
                     'unit_price': str(li.unit_price) if li.unit_price else None,
                     'total_price': str(li.total_price) if li.total_price else None}
                    for li in result.line_items
                ] if hasattr(result, 'line_items') else [],
                repo=get_case_repository(),
                audit_service=get_audit_service(),
            )
    else:
        _logger.debug('CaseEngine: skipped, no tenant_id in state')

    # ── Paperless writeback — enrich document with metadata ────────────────
    if document_ref and document_ref.isdigit():
        try:
            await _writeback_to_paperless(
                document_ref=document_ref,
                analysis=result,
                case_id=case_id,
            )
        except Exception as _wb_exc:
            _logger.warning('Paperless writeback failed for doc %s: %s', document_ref, _wb_exc)

    open_item_id = None
    problem_id = None
    if accounting_review is not None:
        await get_audit_service().log_event(
            {
                'event_id': str(uuid.uuid4()),
                'case_id': case_id,
                'source': state.get('source', 'api'),
                'document_ref': document_ref,
                'agent_name': 'accounting-review',
                'approval_status': 'NOT_REQUIRED',
                'action': 'ACCOUNTING_REVIEW_DRAFT_READY',
                'result': accounting_review.analysis_summary,
                'llm_output': accounting_review.model_dump(mode='json'),
                'policy_refs': policy_refs,
            }
        )
        open_item_id = await _ensure_case_open_item(
            case_id,
            title='Accounting Review durchfuehren',
            description=accounting_review.analysis_summary,
            source='document_analyst',
            desired_status='OPEN',
            document_ref=document_ref,
        )
        await _transition_case_open_items(
            case_id,
            source='document_analyst',
            titles={
                'Accounting Review vorbereiten',
                'Dokumentanalyse pruefen',
                'Dokumentdaten pruefen',
                'Dokumentkonflikt pruefen',
            },
            final_status='COMPLETED',
        )
    elif result.global_decision == 'CONFLICT':
        open_item_id = await _ensure_case_open_item(
            case_id,
            title='Dokumentkonflikt pruefen',
            description=summary,
            source='document_analyst',
            desired_status='OPEN',
            document_ref=document_ref,
        )
        problem_id = await _ensure_problem_case(
            case_id,
            title='Document analysis conflict',
            details=summary,
            document_ref=document_ref,
        )
    elif result.global_decision in {'LOW_CONFIDENCE', 'INCOMPLETE'}:
        desired_status: OpenItemStatus = 'WAITING_DATA' if result.recommended_next_step == 'OCR_RECHECK' else 'OPEN'
        open_item_id = await _ensure_case_open_item(
            case_id,
            title='Dokumentdaten pruefen',
            description=summary,
            source='document_analyst',
            desired_status=desired_status,
            document_ref=document_ref,
        )
        if any(risk.severity == 'HIGH' for risk in result.risks):
            problem_id = await _ensure_problem_case(
                case_id,
                title='Document analysis requires review',
                details=summary,
                document_ref=document_ref,
            )
    else:
        open_item_id = await _ensure_case_open_item(
            case_id,
            title='Dokumentanalyse pruefen',
            description=summary,
            source='document_analyst',
            desired_status='OPEN',
            document_ref=document_ref,
        )

    # ── AUTO mode: close Telegram intake open items when pipeline runs automatically ──
    # When Paperless fires the webhook (source=paperless_webhook), the Telegram
    # [Dokumenteingang pruefen] open item should be auto-completed — no manual trigger needed.
    if state.get('source') == 'paperless_webhook':
        _open_items_svc = get_open_items_service()
        _all_items = await _open_items_svc.list_by_case(case_id)
        for _item in _all_items:
            if (
                _item.source == 'telegram'
                and _item.status in _ACTIVE_ITEM_STATUSES
                and 'Dokumenteingang' in (_item.title or '')
            ):
                await _open_items_svc.update_status(_item.item_id, 'COMPLETED')

    state['policy_refs_consulted'] = policy_refs
    if accounting_review is not None:
        state['accounting_review'] = accounting_review.model_dump(mode='json')
    state['output'] = {
        'status': 'ACCOUNTING_REVIEW' if accounting_review is not None else result.global_decision,
        'approval_mode': 'AUTO',
        'action_key': 'document_analyze',
        'message': 'ACCOUNTING_REVIEW' if accounting_review is not None else result.recommended_next_step,
        'document_analysis': result.model_dump(mode='json'),
        'accounting_review': accounting_review.model_dump(mode='json') if accounting_review is not None else None,
        'recommended_next_step': 'ACCOUNTING_REVIEW' if accounting_review is not None else result.recommended_next_step,
        'ready_for_accounting_review': accounting_review is not None,
        'policy_gate_reason': 'Document analysis completed without critical side effects.',
        'policy_refs': policy_refs,
        'open_item_id': open_item_id,
        'problem_id': problem_id,
        'execution_allowed': False,
    }
    return state


async def run_accounting_analyst(state: AgentState) -> AgentState:
    review_payload = state.get('accounting_review')
    document_payload = state.get('document_analysis')
    if not review_payload or not document_payload:
        return state

    review = AccountingReviewDraft.model_validate(review_payload)
    if review.review_status != 'READY' or not review.ready_for_accounting_review:
        return state

    document_analysis = DocumentAnalysisResult.model_validate(document_payload)
    review_ref = _accounting_review_ref(review)
    accounting_input = AccountingAnalysisInput(
        case_id=state.get('case_id', review.case_id),
        accounting_review_ref=review_ref,
        review_draft=review,
        document_analysis_result=document_analysis,
        case_context=dict(state.get('case_context') or {}),
    )
    accounting_analysis = await get_accounting_analysis_service().analyze(accounting_input)
    policy_refs = _accounting_policy_refs()

    await get_audit_service().log_event(
        {
            'event_id': str(uuid.uuid4()),
            'case_id': review.case_id,
            'source': state.get('source', 'api'),
            'document_ref': review.document_ref,
            'accounting_ref': review_ref,
            'agent_name': 'accounting-analyst',
            'approval_status': 'NOT_REQUIRED',
            'action': 'ACCOUNTING_ANALYSIS_COMPLETED',
            'result': accounting_analysis.analysis_summary,
            'llm_output': accounting_analysis.model_dump(mode='json'),
            'policy_refs': policy_refs,
        }
    )

    output = dict(state.get('output', {}))
    open_item_id = output.get('open_item_id')
    approval_id: str | None = None
    if accounting_analysis.global_decision == 'PROPOSED':
        open_item_id = await _ensure_case_open_item(
            review.case_id,
            title=_accounting_analysis_open_item_title(accounting_analysis),
            description=accounting_analysis.analysis_summary,
            source='accounting_analyst',
            desired_status='PENDING_APPROVAL',
            document_ref=review.document_ref,
            accounting_ref=review_ref,
        )
        await _transition_case_open_items(
            review.case_id,
            source='document_analyst',
            titles={'Accounting Review durchfuehren'},
            final_status='COMPLETED',
        )

        # ── Request user approval (booking_finalize = REQUIRE_USER_APPROVAL) ──
        try:
            _approval_ctx = {
                'accounting_analysis': accounting_analysis.model_dump(mode='json'),
                'document_ref': review.document_ref,
                'accounting_ref': review_ref,
                'source_channel': state.get('source', 'UNKNOWN'),
            }
            _approval = await get_approval_service().request_approval(
                case_id=review.case_id,
                action_type='booking_finalize',
                requested_by='accounting-analyst',
                scope_ref=review_ref,
                reason='Buchungsvorschlag wartet auf Nutzer-Freigabe.',
                policy_refs=policy_refs,
                required_mode='REQUIRE_USER_APPROVAL',
                approval_context=_approval_ctx,
                open_item_id=open_item_id,
                source='accounting_analyst',
            )
            approval_id = _approval.approval_id
        except Exception as _appr_exc:
            _logger.warning('Could not create approval for case %s: %s', review.case_id, _appr_exc)

        # ── Proactive Telegram notification (channel-agnostic) ───────────────
        # Only send if we can find the Telegram chat_id in the case's audit trail.
        try:
            from app.booking.approval_service import format_booking_proposal_message
            _doc_analysis = state.get('document_analysis') or {}
            _annotations_raw = _doc_analysis.get('annotations') or [] if isinstance(_doc_analysis, dict) else []
            from app.document_analysis.models import Annotation as _AnnModel
            _annotations = [_AnnModel.model_validate(a) for a in _annotations_raw if isinstance(a, dict)]
            _proposal_text = format_booking_proposal_message(
                accounting_analysis,
                annotations=_annotations,
                source_channel=state.get('source', 'UNKNOWN'),
            )
            # Append approval_id so user/channel can reference it
            if approval_id:
                _proposal_text += f'\n\n[Ref: {review.case_id} | Freigabe: {approval_id[:8]}]'
            # Look up telegram chat_id from audit events
            _tg_events = await get_audit_service().by_case(review.case_id, limit=200)
            import json as _json
            _chat_id: str | None = None
            for _ev in _tg_events:
                _meta = _ev.llm_output
                if isinstance(_meta, str):
                    try:
                        _meta = _json.loads(_meta)
                    except Exception:
                        _meta = {}
                if isinstance(_meta, dict) and _meta.get('telegram_chat_id'):
                    _chat_id = str(_meta['telegram_chat_id'])
                    break
            # Fallback: case_id mismatch (doc-N vs tg-chat-msg).
            # Look up frya_telegram_case_links for the originating Telegram case
            # that linked to this document case (linked_case_id = review.case_id).
            if not _chat_id:
                try:
                    _tg_link = await get_telegram_case_link_repository().find_latest_trackable_for_linked_case(review.case_id)
                    if _tg_link is None:
                        # Last resort: most-recent link record overall (single-user staging)
                        _recent = await get_telegram_case_link_repository().list_recent(limit=1)
                        _tg_link = _recent[0] if _recent else None
                    if _tg_link and _tg_link.telegram_chat_ref:
                        # telegram_chat_ref format: "tg-chat:{chat_id}"
                        _ref = _tg_link.telegram_chat_ref
                        _chat_id = _ref.split(':', 1)[1] if ':' in _ref else None
                except Exception as _link_exc:
                    _logger.warning('telegram_case_link fallback failed for case %s: %s', review.case_id, _link_exc)
            if _chat_id:
                from app.connectors.contracts import NotificationMessage
                _inline_keyboard = {
                    'inline_keyboard': [
                        [
                            {'text': '✅ Buchen', 'callback_data': f'booking:{review.case_id}:approve'},
                            {'text': '✏️ Korrigieren', 'callback_data': f'booking:{review.case_id}:correct'},
                        ],
                        [
                            {'text': '❌ Ablehnen', 'callback_data': f'booking:{review.case_id}:reject'},
                            {'text': '⏸️ Später', 'callback_data': f'booking:{review.case_id}:defer'},
                        ],
                    ]
                }
                await get_telegram_connector().send(
                    NotificationMessage(
                        target=_chat_id,
                        text=_proposal_text,
                        reply_markup=_inline_keyboard,
                        metadata={
                            'case_id': review.case_id,
                            'approval_id': approval_id,
                            'intent': 'booking.proposal',
                        },
                    )
                )
        except Exception as _notify_exc:
            _logger.warning('Booking proposal notification failed for case %s: %s', review.case_id, _notify_exc)

        output['status'] = 'ACCOUNTING_ANALYST_READY'
        output['approval_id'] = approval_id
    else:
        output['status'] = accounting_analysis.global_decision

    combined_policy_refs = _merge_policy_refs(output.get('policy_refs', []), policy_refs)
    state['policy_refs_consulted'] = combined_policy_refs
    state['accounting_analysis'] = accounting_analysis.model_dump(mode='json')
    output['accounting_analysis'] = accounting_analysis.model_dump(mode='json')
    output['recommended_next_step'] = accounting_analysis.suggested_next_step
    output['ready_for_accounting_confirmation'] = accounting_analysis.ready_for_accounting_confirmation
    output['ready_for_user_approval'] = accounting_analysis.ready_for_user_approval
    output['open_item_id'] = open_item_id
    output['message'] = accounting_analysis.suggested_next_step
    output['policy_refs'] = combined_policy_refs
    output['execution_allowed'] = False
    state['output'] = output
    return state


def _planned_context(state: AgentState) -> dict[str, object]:
    planned = state.get('planned_action', {})
    if not isinstance(planned, dict):
        planned = {}

    missing_fields = planned.get('missing_fields')
    missing_required_data = bool(planned.get('missing_required_data'))
    if isinstance(missing_fields, list) and missing_fields:
        missing_required_data = True

    reversible = planned.get('reversible')
    irreversible = bool(planned.get('irreversible'))
    if reversible is False:
        irreversible = True

    return {
        'confidence': planned.get('confidence'),
        'missing_required_data': missing_required_data,
        'conflict_detected': bool(planned.get('conflict_detected') or planned.get('conflict')),
        'explicit_workflow_rule': bool(planned.get('explicit_workflow_rule') or planned.get('workflow_rule')),
        'deterministic_rule_path': bool(state.get('deterministic_rule_path', False)),
        'side_effect': bool(planned.get('side_effect')),
        'irreversible': irreversible,
        'external_target': bool(planned.get('external_target')),
        'amount_above_threshold': bool(planned.get('amount_above_threshold')),
    }


async def apply_policy_constraints(state: AgentState) -> AgentState:
    policy_access = get_policy_access_layer()
    planned_action = state.get('planned_action', {})
    action_name = ''
    if isinstance(planned_action, dict):
        action_name = str(planned_action.get('action', ''))
    intent = str(state.get('intent', 'UNKNOWN'))

    gate = policy_access.evaluate_gate(intent=intent, action_name=action_name, context=_planned_context(state))
    state['policy_blocked'] = gate.blocked
    state['requires_approval'] = gate.requires_approval
    state['deterministic_rule_path'] = gate.deterministic_rule_path
    state['policy_gate_reason'] = gate.reason
    state['policy_refs_consulted'] = gate.consulted_policy_refs
    state['approval_mode'] = gate.decision_mode  # type: ignore[assignment]
    state['gate_action_key'] = gate.action_key
    state['gate_requires_open_item'] = gate.requires_open_item
    state['gate_requires_problem_case'] = gate.requires_problem_case
    state['execution_allowed'] = gate.execution_allowed
    return state


async def enforce_approval_gate(state: AgentState) -> AgentState:
    planned_action = state.get('planned_action', {})
    action_label = state.get('gate_action_key') or str(planned_action.get('action', 'UNKNOWN_ACTION'))
    gate_reason = state.get('policy_gate_reason', 'Freigabelogik ohne Begruendung.')
    case_id = state.get('case_id', 'uncategorized')

    document_ref = None
    accounting_ref = None
    if isinstance(planned_action, dict):
        raw_doc = planned_action.get('document_ref')
        raw_acc = planned_action.get('accounting_ref')
        document_ref = str(raw_doc) if raw_doc is not None else None
        accounting_ref = str(raw_acc) if raw_acc is not None else None

    approval_mode = state.get('approval_mode', 'PROPOSE_ONLY')
    if state.get('policy_blocked', False) or approval_mode == 'BLOCK_ESCALATE':
        open_item_id = None
        if state.get('gate_requires_open_item', True):
            open_item_id = await _ensure_case_open_item(
                case_id,
                title=f'Blockiert: {action_label}',
                description=gate_reason,
                source='approval_gate',
                desired_status='WAITING_USER',
                document_ref=document_ref,
                accounting_ref=accounting_ref,
            )

        problem_id = None
        if state.get('gate_requires_problem_case', True):
            problem_id = await _ensure_problem_case(
                case_id,
                title=f'Approval block: {action_label}',
                details=gate_reason,
                document_ref=document_ref,
            )

        state['output'] = {
            'status': 'BLOCKED_POLICY',
            'approval_mode': 'BLOCK_ESCALATE',
            'action_key': action_label,
            'message': gate_reason,
            'planned_action': planned_action,
            'policy_gate_reason': gate_reason,
            'policy_refs': state.get('policy_refs_consulted', []),
            'open_item_id': open_item_id,
            'problem_id': problem_id,
            'execution_allowed': False,
        }
        return state

    if approval_mode == 'REQUIRE_USER_APPROVAL':
        approval_service = get_approval_service()

        approved = False
        incoming_approval_id = state.get('approval_id')
        if state.get('approved', False) and incoming_approval_id:
            existing = await approval_service.get(str(incoming_approval_id))
            if existing and existing.status == 'APPROVED' and existing.case_id == case_id:
                approved = True
                state['approval_id'] = existing.approval_id

        if approved:
            state['output'] = {
                'status': 'READY_FOR_DETERMINISTIC_EXECUTION',
                'approval_mode': 'REQUIRE_USER_APPROVAL',
                'action_key': action_label,
                'planned_action': planned_action,
                'deterministic_rule_path': state.get('deterministic_rule_path', False),
                'policy_gate_reason': gate_reason,
                'policy_refs': state.get('policy_refs_consulted', []),
                'execution_allowed': True,
            }
            return state

        approval = await approval_service.request_approval(
            case_id=case_id,
            action_type=action_label,
            scope_ref=planned_action.get('scope_ref') if isinstance(planned_action, dict) else None,
            requested_by='frya-orchestrator',
            reason=gate_reason,
            policy_refs=state.get('policy_refs_consulted', []),
            required_mode='REQUIRE_USER_APPROVAL',
            approval_context={
                'intent': state.get('intent', 'UNKNOWN'),
                'action_key': action_label,
                'deterministic_rule_path': state.get('deterministic_rule_path', False),
            },
            source='approval_gate',
        )

        if not approval.open_item_id:
            open_item_id = await _ensure_case_open_item(
                case_id,
                title=f'Freigabe ausstehend: {action_label}',
                description=gate_reason,
                source='approval_gate',
                desired_status='WAITING_USER',
                document_ref=document_ref,
                accounting_ref=accounting_ref,
            )
            if open_item_id:
                approval = await approval_service.attach_open_item(approval.approval_id, open_item_id) or approval

        state['approval_id'] = approval.approval_id
        state['output'] = {
            'status': 'WAITING_APPROVAL',
            'approval_mode': 'REQUIRE_USER_APPROVAL',
            'action_key': action_label,
            'message': 'Freigabe erforderlich vor Seiteneffekt.',
            'approval_id': approval.approval_id,
            'planned_action': planned_action,
            'policy_gate_reason': gate_reason,
            'policy_refs': state.get('policy_refs_consulted', []),
            'open_item_id': approval.open_item_id,
            'execution_allowed': False,
        }
        return state

    if approval_mode == 'PROPOSE_ONLY':
        open_item_id = None
        if state.get('gate_requires_open_item', True):
            open_item_id = await _ensure_case_open_item(
                case_id,
                title=f'Vorschlag pruefen: {action_label}',
                description=gate_reason,
                source='approval_gate',
                desired_status='OPEN',
                document_ref=document_ref,
                accounting_ref=accounting_ref,
            )

        state['output'] = {
            'status': 'PROPOSE_ONLY',
            'approval_mode': 'PROPOSE_ONLY',
            'action_key': action_label,
            'message': 'Aktion wird nur als Vorschlag bereitgestellt.',
            'planned_action': planned_action,
            'policy_gate_reason': gate_reason,
            'policy_refs': state.get('policy_refs_consulted', []),
            'open_item_id': open_item_id,
            'execution_allowed': False,
        }
        return state

    state['output'] = {
        'status': 'READY_FOR_DETERMINISTIC_EXECUTION',
        'approval_mode': 'AUTO',
        'action_key': action_label,
        'planned_action': planned_action,
        'deterministic_rule_path': state.get('deterministic_rule_path', False),
        'policy_gate_reason': gate_reason,
        'policy_refs': state.get('policy_refs_consulted', []),
        'execution_allowed': True,
    }
    return state
