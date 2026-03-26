"""P-27 A.2 tests: Accounting intents classification."""


def test_classify_financial_query():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Wie viel hab ich diesen Monat ausgegeben') == 'FINANCIAL_QUERY'
    assert classify_intent('Offene Rechnungen') == 'FINANCIAL_QUERY'
    assert classify_intent('Was steht offen') == 'FINANCIAL_QUERY'
    assert classify_intent('Forderungen anzeigen') == 'FINANCIAL_QUERY'


def test_classify_create_invoice():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Erstelle eine Rechnung an Firma Schmidt') == 'CREATE_INVOICE'
    assert classify_intent('Rechnung schreiben') == 'CREATE_INVOICE'


def test_classify_booking_request():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Kannst du das buchen') == 'BOOKING_REQUEST'
    assert classify_intent('Bitte buchen') == 'BOOKING_REQUEST'
    assert classify_intent('Diesen Beleg buchen') == 'BOOKING_REQUEST'


def test_classify_export_request():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Mach mir einen DATEV Export') == 'EXPORT_REQUEST'
    assert classify_intent('Buchungen exportieren') == 'EXPORT_REQUEST'


def test_classify_reminder():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Erinnere mich an die Frist am 15.') == 'REMINDER_PERSONAL'
    assert classify_intent('Deadline setzen') == 'REMINDER_REQUEST'


def test_classify_create_customer():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Leg Firma Mueller als Kunden an') == 'CREATE_CUSTOMER'
    assert classify_intent('Neuen Kunden anlegen') == 'CREATE_CUSTOMER'


def test_existing_intents_still_work():
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Hallo') == 'GREETING'
    assert classify_intent('Was ist der Stand') == 'STATUS_OVERVIEW'
    assert classify_intent('Was brauchst du noch') == 'NEEDS_FROM_USER'
    assert classify_intent('Was kannst du') == 'GENERAL_SAFE_HELP'
    assert classify_intent('Zufaelliger Text ohne Match') == 'GENERAL_CONVERSATION'


def test_risky_substrings_no_longer_block():
    # P-43: _RISKY_SUBSTRINGS removed — Orchestrator is the gatekeeper.
    # These phrases now fall through to GENERAL_CONVERSATION instead of
    # being blocked at the intent-classifier level.
    from app.telegram.communicator.intent_classifier import classify_intent
    assert classify_intent('Freigabe erteilen') == 'GENERAL_CONVERSATION'
    assert classify_intent('Zahlung ausfuehren') == 'GENERAL_CONVERSATION'
