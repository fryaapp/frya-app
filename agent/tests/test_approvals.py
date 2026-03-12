from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalService
from app.audit.repository import AuditRepository
from app.audit.service import AuditService


class _OpenItemsStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.items: dict[str, dict[str, str]] = {}

    async def list_by_case(self, case_id: str):
        return [SimpleNamespace(**item) for item in self.items.values() if item['case_id'] == case_id]

    async def create_item(self, case_id: str, title: str, description: str, source: str = 'agent'):
        item_id = f'auto-{len(self.items) + 1}'
        item = {
            'item_id': item_id,
            'case_id': case_id,
            'title': title,
            'description': description,
            'status': 'OPEN',
            'source': source,
        }
        self.items[item_id] = item
        return SimpleNamespace(**item)

    async def update_status(self, item_id: str, status: str):
        self.calls.append((item_id, status))
        if item_id in self.items:
            self.items[item_id]['status'] = status
            return SimpleNamespace(**self.items[item_id])
        return None


@pytest.mark.asyncio
async def test_approval_lifecycle_memory():
    repo = ApprovalRepository('memory://approvals')
    audit_service = AuditService(AuditRepository('memory://audit'))
    open_items = _OpenItemsStub()
    service = ApprovalService(repo, open_items_service=open_items, audit_service=audit_service)
    await service.initialize()
    await audit_service.initialize()

    requested = await service.request_approval(
        case_id='case-1',
        action_type='post_booking',
        requested_by='orchestrator',
        reason='irreversible',
        policy_refs=[{'policy_name': 'approval_matrix_policy', 'policy_version': '1.0', 'policy_path': 'policies/freigabematrix.md'}],
        required_mode='REQUIRE_USER_APPROVAL',
        approval_context={'intent': 'ACCOUNTING_QUERY'},
    )
    assert requested.status == 'PENDING'

    duplicate = await service.request_approval(
        case_id='case-1',
        action_type='post_booking',
        requested_by='orchestrator',
    )
    assert duplicate.approval_id == requested.approval_id

    attached = await service.attach_open_item(requested.approval_id, 'open-123')
    assert attached is not None
    assert attached.open_item_id == 'open-123'

    decided = await service.decide_approval(requested.approval_id, 'APPROVED', 'maze')
    assert decided is not None
    assert decided.status == 'APPROVED'

    by_case = await service.list_by_case('case-1')
    assert len(by_case) == 1
    assert by_case[0].status == 'APPROVED'

    audit_actions = [item.action for item in await audit_service.by_case('case-1')]
    assert 'APPROVAL_REQUESTED' in audit_actions
    assert 'APPROVAL_STATUS_CHANGED' in audit_actions
    assert ('open-123', 'COMPLETED') in open_items.calls


@pytest.mark.asyncio
async def test_approval_reject_and_revoke_status_mapping():
    repo = ApprovalRepository('memory://approvals')
    audit_service = AuditService(AuditRepository('memory://audit'))
    open_items = _OpenItemsStub()
    service = ApprovalService(repo, open_items_service=open_items, audit_service=audit_service)
    await service.initialize()
    await audit_service.initialize()

    requested = await service.request_approval(
        case_id='case-2',
        action_type='rule_policy_edit',
        requested_by='orchestrator',
    )
    await service.attach_open_item(requested.approval_id, 'open-999')

    rejected = await service.decide_approval(requested.approval_id, 'ABLEHNEN', 'maze')
    assert rejected is not None
    assert rejected.status == 'REJECTED'
    assert ('open-999', 'OPEN') in open_items.calls

    requested_2 = await service.request_approval(
        case_id='case-3',
        action_type='rule_policy_edit',
        requested_by='orchestrator',
    )
    await service.attach_open_item(requested_2.approval_id, 'open-888')

    revoked = await service.decide_approval(requested_2.approval_id, 'REVOKE', 'maze')
    assert revoked is not None
    assert revoked.status == 'REVOKED'
    assert ('open-888', 'CANCELLED') in open_items.calls

    audit_statuses = [item.approval_status for item in await audit_service.recent(limit=10)]
    assert 'REVOKED' in audit_statuses


@pytest.mark.asyncio
async def test_approval_auto_expires_and_blocks_terminal_transition():
    repo = ApprovalRepository('memory://approvals')
    audit_service = AuditService(AuditRepository('memory://audit'))
    service = ApprovalService(repo, audit_service=audit_service)
    await service.initialize()
    await audit_service.initialize()

    requested = await service.request_approval(
        case_id='case-expired',
        action_type='booking_finalize',
        requested_by='orchestrator',
        expires_at=datetime.utcnow() - timedelta(minutes=5),
        reason='timeout',
    )

    expired = await service.get(requested.approval_id)
    assert expired is not None
    assert expired.status == 'EXPIRED'

    with pytest.raises(ValueError, match='Statusuebergang EXPIRED -> APPROVED'):
        await service.decide_approval(requested.approval_id, 'APPROVED', 'maze')

    audit_records = await audit_service.by_case('case-expired')
    assert any(item.action == 'APPROVAL_STATUS_CHANGED' and item.approval_status == 'EXPIRED' for item in audit_records)




def test_approval_repository_normalizes_jsonb_payloads():
    raw = {
        'approval_id': 'a-1',
        'case_id': 'case-jsonb',
        'action_type': 'rule_policy_edit',
        'scope_ref': 'runtime_rules.yaml',
        'required_mode': 'REQUIRE_USER_APPROVAL',
        'approval_context': '{"file_name":"runtime_rules.yaml","reason":"pkg4"}',
        'status': 'PENDING',
        'requested_by': 'admin',
        'requested_at': '2026-03-11 12:00:00',
        'decided_by': None,
        'decided_at': None,
        'expires_at': None,
        'open_item_id': 'oi-1',
        'reason': 'pkg4',
        'policy_refs': '[{"policy_name":"runtime_policy","policy_version":"1.0","policy_path":"policies/runtime_policy.md"}]',
        'audit_event_id': None,
    }

    record = ApprovalRepository._record_from_row(raw)
    assert record.approval_context == {'file_name': 'runtime_rules.yaml', 'reason': 'pkg4'}
    assert record.policy_refs[0]['policy_name'] == 'runtime_policy'
