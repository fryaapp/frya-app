"""Tests for Email Intake → Document Analyst bridge (Paket 58b)."""
import asyncio
import uuid
from datetime import datetime


# ── minimal fakes (same pattern as other test files) ─────────────────────────

class _FakeEvent:
    def __init__(self, action, payload):
        self.action = action
        self.llm_output = payload

class _FakeAuditService:
    def __init__(self):
        self._events = []
        self._case_events = {}
    async def by_case(self, case_id, limit=1000):
        return list(self._case_events.get(case_id, []))[-limit:]
    async def log_event(self, raw):
        action = raw.get('action', '')
        payload = raw.get('llm_output', raw)
        evt = _FakeEvent(action, payload)
        self._events.append(evt)
        cid = raw.get('case_id')
        if cid:
            self._case_events.setdefault(cid, []).append(evt)

class _FakeOpenItem:
    def __init__(self, item_id, title):
        self.item_id = item_id
        self.title = title

class _FakeOpenItemsService:
    def __init__(self):
        self.items = {}
    async def create_item(self, case_id, title, description='', source='', document_ref=None, accounting_ref=None):
        oid = str(uuid.uuid4())
        self.items[oid] = {'case_id': case_id, 'title': title}
        return _FakeOpenItem(oid, title)
    async def update_status(self, oid, status):
        pass

class _FakeRepo:
    def __init__(self):
        self.intakes = {}
        self.attachments = {}
        self.status_updates = {}
        self.att_analyst_updates = {}
    async def initialize(self): pass
    async def create_intake(self, record):
        self.intakes[record.email_intake_id] = record
        return record
    async def add_attachment(self, att):
        self.attachments.setdefault(att.email_intake_id, []).append(att)
        return att
    async def update_status(self, eid, status):
        self.status_updates[eid] = status
    async def update_attachment_count(self, eid, count): pass
    async def update_attachment_analyst(self, att_id, case_id, ctx_ref):
        self.att_analyst_updates[att_id] = {'case_id': case_id, 'ctx_ref': ctx_ref}
    async def get_by_id(self, eid):
        return self.intakes.get(eid)
    async def list_recent(self, limit=50, offset=0):
        return list(self.intakes.values())[:limit]
    async def get_attachments(self, eid):
        return self.attachments.get(eid, [])
    async def find_by_user_ref(self, user_ref, limit=5):
        return [i for i in self.intakes.values() if i.user_ref == user_ref][:limit]
    async def message_id_exists(self, message_id):
        return any(i.message_id == message_id for i in self.intakes.values())

class _FakeFileStore:
    def __init__(self):
        self.written = {}
    def write_bytes(self, path, content):
        self.written[path] = content

def _make_intake_svc(signing_key='test-key'):
    import sys; sys.path.insert(0, '.')
    from app.email_intake.service import EmailIntakeService
    repo = _FakeRepo()
    audit = _FakeAuditService()
    ois = _FakeOpenItemsService()
    fs = _FakeFileStore()
    svc = EmailIntakeService(
        repository=repo, audit_service=audit,
        open_items_service=ois, file_store=fs,
        mailgun_signing_key=signing_key,
    )
    return svc, repo, audit, ois, fs


def _valid_sig(signing_key: str, timestamp: str, token: str) -> str:
    import hmac, hashlib
    h = hmac.new(signing_key.encode('utf-8'), f'{timestamp}{token}'.encode('utf-8'), hashlib.sha256)
    return h.hexdigest()


PASS = '\033[32mPASS\033[0m'
FAIL = '\033[31mFAIL\033[0m'
results = []

def check(name, condition, detail=''):
    status = PASS if condition else FAIL
    results.append(condition)
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))


# ── Test 1: PDF Attachment → Case + Context READY ─────────────────────────

def test_pdf_attachment_creates_case_and_context():
    async def run():
        svc, repo, audit, ois, fs = _make_intake_svc()
        ts, tok = '1710000000', 'tok-abc'
        sig = _valid_sig('test-key', ts, tok)
        record = await svc.handle_webhook(
            timestamp=ts, token=tok, signature=sig,
            sender='lieferant@example.com',
            recipient='frya@myfrya.de',
            subject='Rechnung März 2026',
            body_plain='Anbei unsere Rechnung.',
            message_id='<msg-001@example.com>',
            attachments=[{'file_name': 'rechnung.pdf', 'mime_type': 'application/pdf', 'content': b'%PDF-test'}],
        )
        check('PDF: intake created', record.email_intake_id in repo.intakes)
        check('PDF: status=PROCESSING', repo.status_updates.get(record.email_intake_id) == 'PROCESSING')
        check('PDF: case anlegt (audit events vorhanden)', len(audit._case_events) > 0)
        ctx_events = [e for events in audit._case_events.values() for e in events
                      if e.action == 'DOCUMENT_ANALYST_PENDING']
        check('PDF: DOCUMENT_ANALYST_PENDING event', len(ctx_events) > 0)
        check('PDF: open item created', len(ois.items) > 0)
        case_id = list(audit._case_events.keys())[0]
        check('PDF: case_id starts with email-', case_id.startswith('email-'), case_id)
        check('PDF: attachment analyst update', len(repo.att_analyst_updates) > 0)
    asyncio.run(run())


# ── Test 2: source_channel=EMAIL im Context ───────────────────────────────

def test_source_channel_email():
    async def run():
        import sys; sys.path.insert(0, '.')
        from app.email_intake.analyst_bridge import EmailAnalystBridge
        from app.email_intake.models import EmailIntakeRecord, EmailAttachmentRecord
        audit = _FakeAuditService()
        ois = _FakeOpenItemsService()
        bridge = EmailAnalystBridge(audit, ois)
        intake = EmailIntakeRecord(
            email_intake_id='test-intake-001',
            received_at=datetime.utcnow(),
            sender_email='test@example.com',
            intake_status='RECEIVED',
        )
        att = EmailAttachmentRecord(
            attachment_id='att-001',
            email_intake_id='test-intake-001',
            file_name='doc.pdf',
            mime_type='application/pdf',
            file_size=1000,
            storage_path='email/attachments/2026/03/17/test-intake-001/att-001_doc.pdf',
        )
        ctx = await bridge.create_context_from_attachment(intake, att, 0)
        check('source_channel=EMAIL', ctx.source_channel == 'EMAIL', ctx.source_channel)
        check('media_domain=DOCUMENT', ctx.media_domain == 'DOCUMENT')
        check('telegram_chat_ref contains email:', 'email:' in ctx.telegram_chat_ref)
    asyncio.run(run())


# ── Test 3: Bekannter Absender → confidence=HIGH ──────────────────────────

def test_known_sender_confidence_high():
    async def run():
        from app.email_intake.analyst_bridge import EmailAnalystBridge
        from app.email_intake.models import EmailIntakeRecord, EmailAttachmentRecord
        audit = _FakeAuditService()
        ois = _FakeOpenItemsService()
        bridge = EmailAnalystBridge(audit, ois)
        intake = EmailIntakeRecord(
            email_intake_id='test-intake-002',
            received_at=datetime.utcnow(),
            sender_email='known@example.com',
            user_ref='tg-user-12345',  # known user
            intake_status='RECEIVED',
        )
        att = EmailAttachmentRecord(
            attachment_id='att-002', email_intake_id='test-intake-002',
            file_name='inv.pdf', mime_type='application/pdf', file_size=500,
            storage_path='email/attachments/2026/03/17/test-intake-002/att-002_inv.pdf',
        )
        ctx = await bridge.create_context_from_attachment(intake, att, 0)
        check('Known sender: confidence=MEDIUM', ctx.document_context_link_confidence == 'MEDIUM',
              ctx.document_context_link_confidence)
    asyncio.run(run())


# ── Test 4: Unbekannter Absender → confidence=LOW + open item ─────────────

def test_unknown_sender_confidence_low():
    async def run():
        from app.email_intake.analyst_bridge import EmailAnalystBridge
        from app.email_intake.models import EmailIntakeRecord, EmailAttachmentRecord
        audit = _FakeAuditService()
        ois = _FakeOpenItemsService()
        bridge = EmailAnalystBridge(audit, ois)
        intake = EmailIntakeRecord(
            email_intake_id='test-intake-003',
            received_at=datetime.utcnow(),
            sender_email='unknown@stranger.com',
            # no user_ref
            intake_status='RECEIVED',
        )
        att = EmailAttachmentRecord(
            attachment_id='att-003', email_intake_id='test-intake-003',
            file_name='doc.pdf', mime_type='application/pdf', file_size=200,
            storage_path='email/attachments/2026/03/17/test-intake-003/att-003_doc.pdf',
        )
        ctx = await bridge.create_context_from_attachment(intake, att, 0)
        check('Unknown sender: confidence=LOW', ctx.document_context_link_confidence == 'LOW',
              ctx.document_context_link_confidence)
        check('Unknown sender: open item created', len(ois.items) > 0)
        titles = [v['title'] for v in ois.items.values()]
        check('Unknown sender: open item title mentions E-Mail',
              any('mail' in t.lower() or 'analyst' in t.lower() for t in titles), str(titles))
    asyncio.run(run())


# ── Test 5: "An Analyst weiterleiten" manuell ────────────────────────────

def test_forward_to_analyst_manually():
    async def run():
        svc, repo, audit, ois, fs = _make_intake_svc()
        ts, tok = '1710000001', 'tok-def'
        sig = _valid_sig('test-key', ts, tok)
        # First create via webhook
        record = await svc.handle_webhook(
            timestamp=ts, token=tok, signature=sig,
            sender='manual@example.com', recipient=None, subject='Test',
            body_plain=None, message_id='<msg-002@example.com>',
            attachments=[{'file_name': 'file.pdf', 'mime_type': 'application/pdf', 'content': b'%PDF'}],
        )
        # Reset analyst links so forward_manually has something to do
        for att_id in list(repo.att_analyst_updates.keys()):
            del repo.att_analyst_updates[att_id]
        # Patch attachments to have no analyst_case_id
        atts = repo.attachments.get(record.email_intake_id, [])
        for att in atts:
            att.analyst_case_id = None

        results_list = await svc.forward_to_analyst_manually(
            record.email_intake_id, actor='admin@test'
        )
        check('Manual forward: returns contexts', len(results_list) > 0, str(len(results_list)))
        check('Manual forward: context has source_channel=EMAIL', results_list[0].source_channel == 'EMAIL')
    asyncio.run(run())


# ── Test 6: Mail ohne Anhang → kein Case, kein Analyst-Context ────────────

def test_mail_without_attachment_no_case():
    async def run():
        svc, repo, audit, ois, fs = _make_intake_svc()
        ts, tok = '1710000002', 'tok-ghi'
        sig = _valid_sig('test-key', ts, tok)
        record = await svc.handle_webhook(
            timestamp=ts, token=tok, signature=sig,
            sender='noatt@example.com', recipient=None,
            subject='Nur Text', body_plain='Keine Anhänge.',
            message_id='<msg-003@example.com>',
            attachments=[],  # no attachments
        )
        check('No attachment: intake created', record.email_intake_id in repo.intakes)
        check('No attachment: status stays RECEIVED',
              repo.status_updates.get(record.email_intake_id) != 'PROCESSING',
              repo.status_updates.get(record.email_intake_id, 'RECEIVED'))
        analyst_events = [e for events in audit._case_events.values() for e in events
                          if e.action in {'DOCUMENT_ANALYST_CONTEXT_READY', 'DOCUMENT_ANALYST_PENDING'}]
        check('No attachment: no analyst context created', len(analyst_events) == 0,
              f'found {len(analyst_events)} events')
    asyncio.run(run())


# ── Test 7: Ungültige Signatur → ValueError ──────────────────────────────

def test_invalid_signature_rejected():
    async def run():
        svc, repo, audit, ois, fs = _make_intake_svc()
        try:
            await svc.handle_webhook(
                timestamp='1710000003', token='tok-bad', signature='wrongsig',
                sender='x@example.com', recipient=None, subject=None,
                body_plain=None, message_id=None, attachments=[],
            )
            check('Invalid sig rejected', False, 'no exception raised')
        except ValueError as e:
            check('Invalid sig rejected', 'Signatur' in str(e) or 'signature' in str(e).lower(), str(e))
    asyncio.run(run())


# ── Test 8: Duplicate message_id → duplicate_ignored ──────────────────────

def test_duplicate_message_id():
    async def run():
        svc, repo, audit, ois, fs = _make_intake_svc()
        ts, tok = '1710000004', 'tok-dup'
        sig = _valid_sig('test-key', ts, tok)
        await svc.handle_webhook(
            timestamp=ts, token=tok, signature=sig,
            sender='dup@example.com', recipient=None, subject='First',
            body_plain=None, message_id='<dup-001@example.com>',
            attachments=[],
        )
        # Same message_id again
        try:
            result = await svc.handle_webhook(
                timestamp=ts, token=tok, signature=sig,
                sender='dup@example.com', recipient=None, subject='First',
                body_plain=None, message_id='<dup-001@example.com>',
                attachments=[],
            )
            check('Duplicate: returns existing record', result is not None)
            check('Duplicate: only one intake in repo', len(repo.intakes) == 1,
                  f'found {len(repo.intakes)}')
        except ValueError:
            check('Duplicate: exception expected', True)
    asyncio.run(run())


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    print('\n\033[1mPaket 58b Tests — Email Intake → Document Analyst\033[0m\n')
    test_pdf_attachment_creates_case_and_context()
    test_source_channel_email()
    test_known_sender_confidence_high()
    test_unknown_sender_confidence_low()
    test_forward_to_analyst_manually()
    test_mail_without_attachment_no_case()
    test_invalid_signature_rejected()
    test_duplicate_message_id()
    total = len(results)
    passed = sum(results)
    failed = total - passed
    color = '\033[32m' if not failed else '\033[31m'
    print(f'\n{color}{"="*50}')
    print(f'Paket 58b: {passed}/{total} checks' + (' ✓' if not failed else f'  {failed} FAILED'))
    print(f'{"="*50}\033[0m')
    sys.exit(0 if not failed else 1)
