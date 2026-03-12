from app.audit.repository import AuditRepository


def test_normalize_policy_refs_handles_legacy_string_list():
    raw = '[{"policy_name":"runtime_policy","policy_version":"1.0"}]'
    normalized = AuditRepository._normalize_policy_refs(raw)
    assert isinstance(normalized, list)
    assert len(normalized) == 1
    assert normalized[0]['policy_name'] == 'runtime_policy'


def test_normalize_policy_refs_handles_empty_or_invalid_string():
    assert AuditRepository._normalize_policy_refs('[]') == []
    assert AuditRepository._normalize_policy_refs('invalid') == []


def test_normalize_policy_refs_handles_dict_and_list():
    item = {'policy_name': 'orchestrator_policy', 'policy_version': '2.0'}
    assert AuditRepository._normalize_policy_refs(item) == [item]
    assert AuditRepository._normalize_policy_refs([item]) == [item]