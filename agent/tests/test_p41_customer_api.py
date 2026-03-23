"""Tests for P-41: Kunden-API Endpoints."""
import pytest

def test_customer_router_exists():
    from app.api.customer_api import router
    assert router is not None
    assert router.prefix == '/api/v1'

def test_chat_request_model():
    from app.api.customer_api import ChatRequest, ChatResponse
    req = ChatRequest(message='Hallo')
    assert req.message == 'Hallo'
    resp = ChatResponse(reply='FRYA: Hallo!', case_ref=None, suggestions=[])
    assert resp.reply.startswith('FRYA:')

def test_inbox_item_model():
    from app.api.customer_api import InboxItem
    item = InboxItem(case_id='uuid-123', case_number='CASE-001', vendor_name='Test GmbH',
                     amount=100.0, currency='EUR', document_type='Eingangsrechnung', status='OPEN')
    assert item.vendor_name == 'Test GmbH'

def test_approval_request_valid():
    from app.api.customer_api import ApprovalRequest
    req = ApprovalRequest(action='approve')
    assert req.action == 'approve'

def test_approval_request_invalid():
    import pydantic
    from app.api.customer_api import ApprovalRequest
    with pytest.raises(pydantic.ValidationError):
        ApprovalRequest(action='invalid')

def test_learn_request_model():
    from app.api.customer_api import LearnRequest
    req = LearnRequest(scope='vendor_always', rule='ARAL immer privat')
    assert req.scope == 'vendor_always'

def test_build_suggestions_with_case_ref():
    from app.api.customer_api import _build_suggestions
    s = _build_suggestions('STATUS_OVERVIEW', 'doc-23')
    assert 'Details anzeigen' in s

def test_build_suggestions_greeting():
    from app.api.customer_api import _build_suggestions
    s = _build_suggestions('GREETING', None)
    assert 'Status-Übersicht' in s
