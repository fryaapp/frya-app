from app.telegram.intent_v1 import detect_intent


def test_detect_intent_status():
    intent = detect_intent('status')
    assert intent.name == 'status.overview'


def test_detect_intent_case_show():
    intent = detect_intent('zeige fall case-123')
    assert intent.name == 'case.show'
    assert intent.case_id == 'case-123'


def test_detect_intent_approval():
    intent = detect_intent('freigeben case-abc')
    assert intent.name == 'approval.respond'
    assert intent.decision == 'APPROVED'
    assert intent.target_ref == 'case-abc'


def test_detect_intent_unknown():
    intent = detect_intent('irgendwas komplett anderes')
    assert intent.name == 'unknown'