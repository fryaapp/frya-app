from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ApprovalMode = Literal['AUTO', 'PROPOSE_ONLY', 'REQUIRE_USER_APPROVAL', 'BLOCK_ESCALATE']


@dataclass(slots=True)
class MatrixRule:
    action_key: str
    default_mode: ApprovalMode
    keywords: tuple[str, ...]
    allow_auto_with_rule: bool = False
    never_auto: bool = False
    always_block: bool = False
    strict_require: bool = False


@dataclass(slots=True)
class MatrixDecision:
    action_key: str
    mode: ApprovalMode
    reason: str
    requires_open_item: bool
    requires_problem_case: bool
    execution_allowed: bool


DEFAULT_MATRIX_RULES: tuple[MatrixRule, ...] = (
    MatrixRule('document_type_detect', 'AUTO', ('document_type', 'classify_document', 'doktyp', 'document classify')),
    MatrixRule('tags_set', 'AUTO', ('set_tag', 'tag', 'tags')),
    MatrixRule('correspondent_assign', 'AUTO', ('correspondent', 'assign_vendor', 'assign_contact', 'korrespondent')),
    MatrixRule('ocr_reanalyze', 'AUTO', ('ocr_reanalyze', 'ocr_retry', 'tika_reanalyze', 'ocr')),
    MatrixRule('rule_policy_edit', 'REQUIRE_USER_APPROVAL', ('rule_edit', 'policy_edit', 'rules_update', 'policy_update'), never_auto=True, strict_require=True),
    MatrixRule('booking_create', 'PROPOSE_ONLY', ('bill_draft', 'invoice_draft', 'booking_draft', 'draft_create'), allow_auto_with_rule=True),
    MatrixRule('booking_proposal_create', 'PROPOSE_ONLY', ('booking_proposal', 'buchungsvorschlag', 'posting_proposal')),
    MatrixRule('booking_finalize', 'REQUIRE_USER_APPROVAL', ('post_booking', 'booking_finalize', 'finalize_booking', 'buchung_finalisieren'), allow_auto_with_rule=True, strict_require=True),
    MatrixRule('payment_proposal_create', 'PROPOSE_ONLY', ('payment_proposal', 'zahlungsvorschlag'), allow_auto_with_rule=True),
    MatrixRule('payment_execute', 'BLOCK_ESCALATE', ('payment_execute', 'payment_post', 'zahlung_ausfuehren', 'zahlung_buchen'), always_block=True, never_auto=True),
    MatrixRule('document_mark_done', 'PROPOSE_ONLY', ('document_done', 'mark_done', 'erledigt_markieren'), allow_auto_with_rule=True),
    MatrixRule('open_item_create', 'AUTO', ('open_item_create', 'wiedervorlage_anlegen', 'create_open_item')),
    MatrixRule('reminder_send', 'PROPOSE_ONLY', ('send_reminder', 'reminder_send', 'reminder'), allow_auto_with_rule=True),
    MatrixRule('problem_case_create', 'AUTO', ('problem_case_create', 'problemfall', 'exception_record')),
    MatrixRule('human_readable_review_generate', 'AUTO', ('review_view', 'pruefsicht', 'human_readable_review')),
    MatrixRule('recurring_document_draft_create', 'PROPOSE_ONLY', ('recurring_draft', 'repeat_invoice_draft', 'wiederkehrend'), allow_auto_with_rule=True),
    MatrixRule('correction_case_mark', 'AUTO', ('mark_correction', 'korrekturfall', 'correction_mark')),
    MatrixRule('side_effect_run_start', 'REQUIRE_USER_APPROVAL', ('side_effect', 'execute_workflow', 'trigger_workflow', 'agent_run_with_side_effect'), allow_auto_with_rule=True, strict_require=True),
)


_MODE_ORDER: tuple[ApprovalMode, ...] = ('AUTO', 'PROPOSE_ONLY', 'REQUIRE_USER_APPROVAL', 'BLOCK_ESCALATE')


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return parsed


def _normalize_action_name(action_name: str) -> str:
    return (action_name or '').strip().lower().replace('-', '_').replace(' ', '_')


def _mode_index(mode: ApprovalMode) -> int:
    return _MODE_ORDER.index(mode)


def _escalate(mode: ApprovalMode, steps: int = 1) -> ApprovalMode:
    idx = min(_mode_index(mode) + steps, len(_MODE_ORDER) - 1)
    return _MODE_ORDER[idx]


def _build_rule_index(matrix_payload: dict[str, Any] | None) -> dict[str, MatrixRule]:
    index: dict[str, MatrixRule] = {rule.action_key: rule for rule in DEFAULT_MATRIX_RULES}
    if not isinstance(matrix_payload, dict):
        return index

    entries = matrix_payload.get('rules')
    if not isinstance(entries, list):
        return index

    for raw in entries:
        if not isinstance(raw, dict):
            continue
        action_key = str(raw.get('action') or raw.get('action_key') or '').strip()
        if not action_key:
            continue
        mode = str(raw.get('default_mode') or raw.get('mode') or '').strip().upper()
        if mode not in _MODE_ORDER:
            continue
        raw_keywords = raw.get('keywords')
        keywords: tuple[str, ...]
        if isinstance(raw_keywords, list):
            keywords = tuple(str(x).strip().lower() for x in raw_keywords if str(x).strip())
        else:
            keywords = ()
        base = index.get(action_key, MatrixRule(action_key=action_key, default_mode='PROPOSE_ONLY', keywords=()))
        index[action_key] = MatrixRule(
            action_key=action_key,
            default_mode=mode,  # type: ignore[arg-type]
            keywords=keywords or base.keywords,
            allow_auto_with_rule=bool(raw.get('allow_auto_with_rule', base.allow_auto_with_rule)),
            never_auto=bool(raw.get('never_auto', base.never_auto)),
            always_block=bool(raw.get('always_block', base.always_block)),
            strict_require=bool(raw.get('strict_require', base.strict_require)),
        )
    return index


def _infer_action_key(action_name: str, rules: dict[str, MatrixRule]) -> str:
    normalized = _normalize_action_name(action_name)
    if not normalized or normalized == 'none':
        return 'unknown_action'

    if normalized in rules:
        return normalized

    for key, rule in rules.items():
        if normalized == key:
            return key
        for kw in rule.keywords:
            if kw and kw in normalized:
                return key
    return 'unknown_action'


def evaluate_approval_mode(
    action_name: str,
    *,
    context: dict[str, Any] | None = None,
    matrix_payload: dict[str, Any] | None = None,
) -> MatrixDecision:
    ctx = context or {}
    rules = _build_rule_index(matrix_payload)
    action_key = _infer_action_key(action_name, rules)
    rule = rules.get(action_key)

    reasons: list[str] = []
    confidence = _safe_float(ctx.get('confidence'))
    missing_required_data = bool(ctx.get('missing_required_data'))
    conflict_detected = bool(ctx.get('conflict_detected'))
    explicit_workflow_rule = bool(ctx.get('explicit_workflow_rule'))
    irreversible = bool(ctx.get('irreversible'))
    side_effect = bool(ctx.get('side_effect'))
    external_target = bool(ctx.get('external_target'))
    amount_above_threshold = bool(ctx.get('amount_above_threshold'))

    if rule is None:
        if irreversible or side_effect:
            mode: ApprovalMode = 'BLOCK_ESCALATE'
            reasons.append('Unbekannte Seiteneffekt-/Risikoaktion ohne Matrix-Rule.')
        else:
            mode = 'PROPOSE_ONLY'
            reasons.append('Unbekannte Aktion, daher Vorschlagsmodus.')
    else:
        mode = rule.default_mode
        reasons.append(f'Standardmodus aus Freigabematrix: {rule.default_mode}.')

        if rule.always_block:
            mode = 'BLOCK_ESCALATE'
            reasons.append('Aktion ist in der Matrix als blockiert markiert.')

        if rule.never_auto and mode == 'AUTO':
            mode = 'PROPOSE_ONLY'
            reasons.append('Aktion ist als never_auto markiert.')

        if explicit_workflow_rule and rule.allow_auto_with_rule and not rule.always_block:
            mode = 'AUTO'
            reasons.append('Expliziter deterministischer Workflow-Regelpfad aktiv.')

    if missing_required_data:
        mode = 'BLOCK_ESCALATE'
        reasons.append('Pflichtdaten fehlen.')

    if conflict_detected:
        mode = _escalate(mode)
        reasons.append('Konflikt erkannt, Modus hochgestuft.')

    if confidence is not None:
        if confidence < 0.75:
            mode = _escalate(mode)
            reasons.append(f'Confidence niedrig ({confidence:.2f}), Modus hochgestuft.')
        if confidence < 0.45:
            mode = _escalate(mode)
            reasons.append(f'Confidence kritisch ({confidence:.2f}), erneut hochgestuft.')

    if amount_above_threshold:
        mode = _escalate(mode)
        reasons.append('Betrag oberhalb Schwellenwert.')

    if external_target and action_key == 'reminder_send':
        mode = _escalate(mode)
        reasons.append('Externer Empfaenger fuer Reminder erkannt.')

    if rule and rule.strict_require and not explicit_workflow_rule and mode != 'BLOCK_ESCALATE':
        mode = 'REQUIRE_USER_APPROVAL'
        reasons.append('Aktion ist strict_require ohne expliziten Workflow-Bypass.')

    if irreversible and mode == 'AUTO' and not explicit_workflow_rule:
        mode = 'REQUIRE_USER_APPROVAL'
        reasons.append('Irreversible Aktion ohne expliziten Workflow-Regelpfad.')

    if action_key == 'payment_execute':
        mode = 'BLOCK_ESCALATE'
        reasons.append('Zahlungsausfuehrung ist im aktuellen Betriebsmodus blockiert.')

    return MatrixDecision(
        action_key=action_key,
        mode=mode,
        reason=' '.join(reasons) if reasons else 'Keine Regelbegruendung vorhanden.',
        requires_open_item=mode in {'PROPOSE_ONLY', 'REQUIRE_USER_APPROVAL', 'BLOCK_ESCALATE'},
        requires_problem_case=mode == 'BLOCK_ESCALATE',
        execution_allowed=mode == 'AUTO',
    )
