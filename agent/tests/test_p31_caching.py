"""P-31 tests: Prompt caching for Communicator."""


def test_communicator_cache_control_anthropic():
    """System-Prompt has cache_control flag for Anthropic provider."""
    from app.telegram.communicator.service import build_llm_context_payload
    from app.telegram.communicator.models import CommunicatorContextResolution
    from app.telegram.communicator.memory.truth_arbitration import TruthAnnotation

    truth = TruthAnnotation(truth_basis='LIVE_CONTEXT', requires_uncertainty_phrase=False, priority=1)
    payload = build_llm_context_payload(
        intent='GREETING',
        context_resolution=None,
        truth_annotation=truth,
        conversation_memory=None,
        user_message='hallo',
        provider='anthropic',
    )
    sys_msg = payload['messages'][0]
    assert isinstance(sys_msg['content'], list), 'System content must be array for Anthropic'
    assert sys_msg['content'][0]['cache_control'] == {'type': 'ephemeral'}


def test_no_cache_control_for_ionos():
    """IONOS agents don't get cache_control."""
    from app.telegram.communicator.service import build_llm_context_payload
    from app.telegram.communicator.memory.truth_arbitration import TruthAnnotation

    truth = TruthAnnotation(truth_basis='LIVE_CONTEXT', requires_uncertainty_phrase=False, priority=1)
    payload = build_llm_context_payload(
        intent='GREETING',
        context_resolution=None,
        truth_annotation=truth,
        conversation_memory=None,
        user_message='hallo',
        provider='ionos',
    )
    sys_msg = payload['messages'][0]
    assert isinstance(sys_msg['content'], str), 'System content must be string for non-Anthropic'


def test_no_cache_control_default():
    """No provider → no cache_control (backwards compatible)."""
    from app.telegram.communicator.service import build_llm_context_payload
    from app.telegram.communicator.memory.truth_arbitration import TruthAnnotation

    truth = TruthAnnotation(truth_basis='LIVE_CONTEXT', requires_uncertainty_phrase=False, priority=1)
    payload = build_llm_context_payload(
        intent='GREETING',
        context_resolution=None,
        truth_annotation=truth,
        conversation_memory=None,
        user_message='hallo',
    )
    sys_msg = payload['messages'][0]
    assert isinstance(sys_msg['content'], str)
