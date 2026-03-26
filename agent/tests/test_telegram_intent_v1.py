from app.telegram.intent_v1 import detect_intent


def test_detect_intent_status():
    intent = detect_intent('status')
    assert intent.name == 'status.overview'


def test_detect_intent_help():
    intent = detect_intent('/start')
    assert intent.name == 'help.basic'


def test_detect_intent_unknown_routes_to_manual_queue():
    intent = detect_intent('bitte schau mal auf die letzte rueckfrage')
    assert intent.name == 'unknown'


def test_detect_intent_unknown():
    intent = detect_intent('irgendwas komplett anderes')
    assert intent.name == 'unknown'
