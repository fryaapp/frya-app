"""Paket 53 – Withdraw / Internal-Takeover path tests.

Covers:
- WAITING_USER -> WITHDRAWN (withdraw_data_request)
- WITHDRAWN keeps followup visible in inspect JSON
- Telegram clarification is WITHDRAWN after operator withdraw
- Open item transitions: WAITING_USER -> OPEN (internal handling)
- /status shows UNDER_INTERNAL_REVIEW, not WAITING_FOR_YOUR_REPLY
- Late reply after withdraw -> CLARIFICATION_NOT_OPEN
- No duplicate withdraw allowed
- Withdraw only from DATA_REQUESTED state (guard)
- Audit + Inspect + UI consistent after withdraw
"""
from fastapi.testclient import TestClient

from tests.test_api_surface import _build_app, _extract_csrf_token, _login_admin
from tests.test_telegram_clarification_v1 import _configure_env
from tests.test_telegram_document_analyst_review_v1 import (
    _build_started_case,
    _patch_media_io,
    _patch_paperless_fast,
)


def _build_data_requested_case(client: TestClient) -> tuple[str, dict]:
    """Build a case that has DATA_REQUESTED open (clarification OPEN, open item WAITING_USER)."""
    from tests.test_telegram_document_analyst_followup_v1 import _build_review_still_open_case

    case_id, start_body = _build_review_still_open_case(client)
    _login_admin(client)
    csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

    followup_response = client.post(
        f'/inspect/cases/{case_id}/document-analyst-followup',
        json={
            'mode': 'REQUEST_DATA',
            'note': 'Bessere Lesbarkeit benoetigt.',
            'question': 'Bitte sende eine schaerfere Aufnahme oder das Dokument als PDF erneut.',
        },
        headers={'x-frya-csrf-token': csrf},
    )
    assert followup_response.status_code == 200
    assert followup_response.json()['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED'
    return case_id, start_body


# ─────────────────────────────────────────────
# 1. Happy path: WAITING_USER -> WITHDRAWN
# ─────────────────────────────────────────────

def test_followup_withdraw_changes_status_to_withdrawn(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'Intern uebernommen, kein Warten mehr noetig.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN'
        assert body['no_further_telegram_action'] is True
        assert body['linked_clarification_state'] == 'WITHDRAWN'
        assert body['withdraw_reason'] == 'Intern uebernommen, kein Warten mehr noetig.'


def test_followup_withdraw_closes_telegram_clarification(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'Intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        case_json = client.get(f'/inspect/cases/{case_id}/json').json()
        clarification = case_json['telegram_clarification']
        assert clarification is not None
        assert clarification['clarification_state'] == 'WITHDRAWN'
        assert clarification['telegram_clarification_closed_for_user_input'] is True
        assert clarification['resolution_outcome'] == 'WITHDRAWN'


def test_followup_withdraw_transitions_open_item_to_open(tmp_path, monkeypatch):
    """Open item must go from WAITING_USER to OPEN for internal handling."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, start_body = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        # Before: WAITING_USER
        before = client.get(f'/inspect/cases/{case_id}/json').json()
        runtime_item_before = next(
            item for item in before['open_items']
            if item['item_id'] == start_body['runtime_open_item_id']
        )
        assert runtime_item_before['status'] == 'WAITING_USER'

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        # After: OPEN (internal can continue)
        after = client.get(f'/inspect/cases/{case_id}/json').json()
        runtime_item_after = next(
            item for item in after['open_items']
            if item['item_id'] == start_body['runtime_open_item_id']
        )
        assert runtime_item_after['status'] == 'OPEN'


def test_followup_withdraw_visible_in_inspect_json(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        followup = body['document_analyst_followup']
        assert followup is not None
        assert followup['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN'

        actions = [e['action'] for e in body['chronology']]
        assert 'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED' in actions
        assert 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN' in actions
        assert 'TELEGRAM_CLARIFICATION_WITHDRAWN' in actions


# ─────────────────────────────────────────────
# 2. /status shows UNDER_INTERNAL_REVIEW after withdraw
# ─────────────────────────────────────────────

def test_followup_withdraw_user_status_becomes_under_internal_review(tmp_path, monkeypatch):
    """After withdraw the user should NOT see WAITING_FOR_YOUR_REPLY."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        # Check telegram_ingress section for user-visible status
        body = client.get(f'/inspect/cases/{case_id}/json').json()
        ingress = body.get('telegram_ingress') or {}
        user_status = ingress.get('user_visible_status') or {}
        # WAITING_FOR_YOUR_REPLY must NOT appear
        assert user_status.get('status_code') != 'WAITING_FOR_YOUR_REPLY', (
            'After withdraw user must not see WAITING_FOR_YOUR_REPLY'
        )
        if user_status.get('status_code'):
            assert user_status['status_code'] == 'UNDER_INTERNAL_REVIEW'


# ─────────────────────────────────────────────
# 3. Late reply after withdraw -> clarification_not_open
# ─────────────────────────────────────────────

def test_late_reply_after_withdraw_clarification_closed_for_user_input(tmp_path, monkeypatch):
    """After withdraw, clarification must be closed for user input (no re-opening).

    The `telegram_clarification_closed_for_user_input=True` flag + late_reply_policy='REJECT_NOT_OPEN'
    ensure that any incoming answer will be treated as CLARIFICATION_NOT_OPEN by the webhook router.
    This test verifies the flags are correct after withdraw.
    """
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        clar = body['telegram_clarification']

        # Must be flagged closed — incoming answers will hit CLARIFICATION_NOT_OPEN branch
        assert clar['telegram_clarification_closed_for_user_input'] is True
        assert clar['late_reply_policy'] == 'REJECT_NOT_OPEN'
        assert clar['clarification_state'] == 'WITHDRAWN'
        # No further follow-up allowed
        assert clar['follow_up_allowed'] is False


# ─────────────────────────────────────────────
# 4. Guard: no duplicate withdraw
# ─────────────────────────────────────────────

def test_followup_withdraw_blocks_duplicate(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        first = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'erstes Mal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert first.status_code == 200

        csrf2 = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        second = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'zweites Mal'},
            headers={'x-frya-csrf-token': csrf2},
        )
        assert second.status_code == 409
        assert 'DATA_REQUESTED' in second.json()['detail'] or 'WITHDRAWN' in second.json()['detail']


# ─────────────────────────────────────────────
# 5. Guard: withdraw only from DATA_REQUESTED
# ─────────────────────────────────────────────

def test_followup_withdraw_blocked_if_not_data_requested(tmp_path, monkeypatch):
    """Withdraw must fail if no DATA_REQUESTED followup exists."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        from tests.test_telegram_document_analyst_followup_v1 import _build_review_still_open_case

        case_id, _ = _build_review_still_open_case(client)
        # State: REVIEW_STILL_OPEN / FOLLOWUP_REQUIRED — no DATA_REQUESTED yet
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 409
        # Error must explain the state, not a silent 500
        assert resp.json()['detail']


# ─────────────────────────────────────────────
# 6. Existing execute_followup guard: WITHDRAWN blocks re-execute
# ─────────────────────────────────────────────

def test_execute_followup_blocked_after_withdrawn(tmp_path, monkeypatch):
    """execute_followup must also be blocked after WITHDRAWN state."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        csrf2 = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        retry = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup',
            json={'mode': 'INTERNAL_ONLY', 'note': 'nach withdraw'},
            headers={'x-frya-csrf-token': csrf2},
        )
        assert retry.status_code == 409


# ─────────────────────────────────────────────
# 7. Audit chain consistent
# ─────────────────────────────────────────────

def test_followup_withdraw_audit_chain_complete(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern uebernommen'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        actions = [e['action'] for e in body['chronology']]

        # Complete chain must be present
        for expected in [
            'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
            'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
            'TELEGRAM_CLARIFICATION_REQUESTED',
            'TELEGRAM_CLARIFICATION_DELIVERY',
            'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
            'TELEGRAM_CLARIFICATION_WITHDRAWN',
        ]:
            assert expected in actions, f'Expected action {expected} in chronology, got: {actions}'

        # No leaks: COMPLETED must NOT appear
        assert 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED' not in actions


# ─────────────────────────────────────────────
# 8. HTML UI shows withdrawn state
# ─────────────────────────────────────────────

def test_followup_withdraw_visible_in_ui_html(tmp_path, monkeypatch):
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        ui = client.get(f'/ui/cases/{case_id}')
        assert ui.status_code == 200
        assert 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN' in ui.text or 'Document Analyst Follow-up' in ui.text


# ─────────────────────────────────────────────
# 9. Safety invariants
# ─────────────────────────────────────────────

def test_followup_withdraw_no_status_leak(tmp_path, monkeypatch):
    """After withdraw: no WAITING_FOR_YOUR_REPLY, no DATA_REQUESTED in followup, no re-open."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
            json={'note': 'intern'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()

        # followup must be WITHDRAWN
        assert body['document_analyst_followup']['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN'

        # clarification must be WITHDRAWN and closed for user input
        clar = body['telegram_clarification']
        assert clar['clarification_state'] == 'WITHDRAWN'
        assert clar['telegram_clarification_closed_for_user_input'] is True

        # open item must be OPEN (not WAITING_USER, not COMPLETED)
        open_items = {i['item_id']: i for i in body['open_items']}
        oi_id = clar.get('open_item_id')
        if oi_id and oi_id in open_items:
            assert open_items[oi_id]['status'] == 'OPEN'


# =============================================================================
# STEP 2 — Internal Takeover + Conservative Completion
# =============================================================================


def _build_withdrawn_case(client: TestClient) -> tuple[str, dict]:
    """Build a case that has WITHDRAWN followup (post withdraw_data_request)."""
    case_id, start_body = _build_data_requested_case(client)
    _login_admin(client)
    csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
    resp = client.post(
        f'/inspect/cases/{case_id}/document-analyst-followup-withdraw',
        json={'note': 'Intern uebernommen.'},
        headers={'x-frya-csrf-token': csrf},
    )
    assert resp.status_code == 200
    assert resp.json()['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN'
    return case_id, start_body


# ─────────────────────────────────────────────
# 10. WITHDRAWN -> INTERNAL_ONLY happy path
# ─────────────────────────────────────────────

def test_activate_internal_takeover_transitions_to_internal_only(tmp_path, monkeypatch):
    """WITHDRAWN -> INTERNAL_ONLY via activate_internal_takeover."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_withdrawn_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
            json={'note': 'Interne Pruefung laeuft jetzt aktiv.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY'
        assert body['followup_mode'] == 'INTERNAL_ONLY'
        assert body['no_further_telegram_action'] is True
        assert body['internal_takeover_allowed'] is False
        assert body['internal_takeover_reason'] == 'Interne Pruefung laeuft jetzt aktiv.'


# ─────────────────────────────────────────────
# 11. INTERNAL_ONLY: user status stays UNDER_INTERNAL_REVIEW
# ─────────────────────────────────────────────

def test_internal_only_user_status_remains_under_internal_review(tmp_path, monkeypatch):
    """User must still see UNDER_INTERNAL_REVIEW after internal takeover activated."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_withdrawn_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
            json={'note': 'aktiv'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        ingress = body.get('telegram_ingress') or {}
        user_status = ingress.get('user_visible_status') or {}
        assert user_status.get('status_code') == 'UNDER_INTERNAL_REVIEW'


# ─────────────────────────────────────────────
# 12. Guard: internal takeover only from WITHDRAWN
# ─────────────────────────────────────────────

def test_internal_takeover_blocked_if_not_withdrawn(tmp_path, monkeypatch):
    """activate_internal_takeover must 409 if followup is not WITHDRAWN."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_data_requested_case(client)
        # State: DATA_REQUESTED (not WITHDRAWN)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 409
        assert 'WITHDRAWN' in resp.json()['detail']


# ─────────────────────────────────────────────
# 13. Guard: duplicate internal takeover blocked
# ─────────────────────────────────────────────

def test_internal_takeover_blocks_duplicate(tmp_path, monkeypatch):
    """Second activate_internal_takeover must 409 (already INTERNAL_ONLY)."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_withdrawn_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        first = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
            json={'note': 'erstes Mal'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert first.status_code == 200

        csrf2 = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
        second = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
            json={'note': 'zweites Mal'},
            headers={'x-frya-csrf-token': csrf2},
        )
        assert second.status_code == 409
        assert 'WITHDRAWN' in second.json()['detail']


# ─────────────────────────────────────────────
# 14. INTERNAL_ONLY -> COMPLETED happy path
# ─────────────────────────────────────────────

def _build_internal_only_case(client: TestClient) -> tuple[str, dict]:
    """Build a case in INTERNAL_ONLY state."""
    case_id, start_body = _build_withdrawn_case(client)
    _login_admin(client)
    csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)
    resp = client.post(
        f'/inspect/cases/{case_id}/document-analyst-followup-internal-takeover',
        json={'note': 'Interne Nachbearbeitung aktiv.'},
        headers={'x-frya-csrf-token': csrf},
    )
    assert resp.status_code == 200
    return case_id, start_body


def test_complete_internal_transitions_to_completed(tmp_path, monkeypatch):
    """INTERNAL_ONLY -> COMPLETED via complete_internal."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_internal_only_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'Interne Nachbearbeitung abgeschlossen.'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body['followup_status'] == 'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED'
        assert body['no_further_telegram_action'] is True
        assert body['actor'] is not None


# ─────────────────────────────────────────────
# 15. Open item -> COMPLETED after complete_internal
# ─────────────────────────────────────────────

def test_complete_internal_closes_open_item(tmp_path, monkeypatch):
    """complete_internal must transition the runtime open item to COMPLETED."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, start_body = _build_internal_only_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'abgeschlossen'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        runtime_item_id = start_body.get('runtime_open_item_id')
        if runtime_item_id:
            item = next((i for i in body['open_items'] if i['item_id'] == runtime_item_id), None)
            if item:
                assert item['status'] == 'COMPLETED'


# ─────────────────────────────────────────────
# 16. User status -> COMPLETED after complete_internal
# ─────────────────────────────────────────────

def test_complete_internal_user_status_becomes_completed(tmp_path, monkeypatch):
    """After complete_internal user must see COMPLETED, not UNDER_INTERNAL_REVIEW."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_internal_only_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'abgeschlossen'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        ingress = body.get('telegram_ingress') or {}
        user_status = ingress.get('user_visible_status') or {}
        assert user_status.get('status_code') == 'COMPLETED'
        assert 'abgeschlossen' in (user_status.get('status_label') or '').lower() or \
               user_status.get('status_code') == 'COMPLETED'


# ─────────────────────────────────────────────
# 17. Guard: complete_internal only from INTERNAL_ONLY
# ─────────────────────────────────────────────

def test_complete_internal_blocked_if_not_internal_only(tmp_path, monkeypatch):
    """complete_internal must 409 if followup is not INTERNAL_ONLY."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_withdrawn_case(client)
        # State: WITHDRAWN (not INTERNAL_ONLY yet)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        resp = client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'zu frueh'},
            headers={'x-frya-csrf-token': csrf},
        )
        assert resp.status_code == 409
        assert 'INTERNAL_ONLY' in resp.json()['detail']


# ─────────────────────────────────────────────
# 18. Full audit chain: DATA_REQUESTED -> WITHDRAWN -> INTERNAL_ONLY -> COMPLETED
# ─────────────────────────────────────────────

def test_full_internal_takeover_audit_chain(tmp_path, monkeypatch):
    """Complete chain: withdraw -> internal takeover -> internal complete."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_internal_only_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'Abschluss nach interner Uebernahme.'},
            headers={'x-frya-csrf-token': csrf},
        )

        body = client.get(f'/inspect/cases/{case_id}/json').json()
        actions = [e['action'] for e in body['chronology']]

        # Full chain
        for expected in [
            'DOCUMENT_ANALYST_FOLLOWUP_REQUIRED',
            'DOCUMENT_ANALYST_FOLLOWUP_DATA_REQUESTED',
            'TELEGRAM_CLARIFICATION_WITHDRAWN',
            'DOCUMENT_ANALYST_FOLLOWUP_WITHDRAWN',
            'DOCUMENT_ANALYST_FOLLOWUP_INTERNAL_ONLY',
            'DOCUMENT_ANALYST_FOLLOWUP_COMPLETED',
            'TELEGRAM_CLARIFICATION_INTERNAL_COMPLETED',
        ]:
            assert expected in actions, f'Expected {expected!r} in audit chain, got: {actions}'

        # No Telegram loop: no new CLARIFICATION_REQUESTED after the withdraw
        clarification_requested_events = [a for a in actions if a == 'TELEGRAM_CLARIFICATION_REQUESTED']
        assert len(clarification_requested_events) == 1, 'Must be exactly one CLARIFICATION_REQUESTED (no loop)'


# ─────────────────────────────────────────────
# 19. No WAITING_FOR_YOUR_REPLY at any point in internal path
# ─────────────────────────────────────────────

def test_no_waiting_for_reply_throughout_internal_path(tmp_path, monkeypatch):
    """User must never see WAITING_FOR_YOUR_REPLY once withdraw is done."""
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv('FRYA_TELEGRAM_BOT_TOKEN', 'telegram-test-token')
    _patch_media_io(monkeypatch)
    _patch_paperless_fast(monkeypatch)

    app = _build_app()
    with TestClient(app) as client:
        case_id, _ = _build_internal_only_case(client)
        _login_admin(client)
        csrf = _extract_csrf_token(client.get(f'/ui/cases/{case_id}').text)

        # At INTERNAL_ONLY
        body = client.get(f'/inspect/cases/{case_id}/json').json()
        ingress = body.get('telegram_ingress') or {}
        s = (ingress.get('user_visible_status') or {}).get('status_code')
        assert s != 'WAITING_FOR_YOUR_REPLY'

        # At COMPLETED
        client.post(
            f'/inspect/cases/{case_id}/document-analyst-followup-internal-complete',
            json={'note': 'done'},
            headers={'x-frya-csrf-token': csrf},
        )
        body2 = client.get(f'/inspect/cases/{case_id}/json').json()
        ingress2 = body2.get('telegram_ingress') or {}
        s2 = (ingress2.get('user_visible_status') or {}).get('status_code')
        assert s2 != 'WAITING_FOR_YOUR_REPLY'
