from __future__ import annotations

from app.telegram.communicator.models import CommunicatorIntentCode

# ── Risky substrings (override all other intents) ─────────────────────────────
# Checked case-insensitively against lowercased text.
_RISKY_SUBSTRINGS: tuple[str, ...] = (
    # Finance / execution
    'freigabe',
    'freigeben',
    'genehmige',
    'bestaetige',
    'zahlung',
    'zahle',
    'bezahl',
    'buche ',  # trailing space avoids "buchen" false positive in phrases
    'ueberweise',
    'loesche',
    'starte ocr',
    'mach die zahlung',
    'approve',
    'delete',
    # Cross-case navigation
    'alle faelle',
    'alle vorgaenge',
    'alle akten',
    'zeig mir alle',
    'liste all',  # matches "liste alle" and "liste aller"
    # File-send
    'schick mir das dokument',
    'schick mir die datei',
    'schick mir das bild',
    'schick mir das pdf',
    'lade das dokument',
    'send me the',
    'forward the document',
)

# ── Greeting ──────────────────────────────────────────────────────────────────
_GREETING_TOKENS: frozenset[str] = frozenset({
    'hallo', 'hi', 'hey', 'servus', 'moin', 'na', 'jo',
})
_GREETING_PHRASES: tuple[str, ...] = (
    'guten morgen',
    'guten tag',
    'guten abend',
    'hi frya',
    'hallo frya',
    'hey frya',
    'bist du da',
    'grüß dich',
    'gruess dich',
    'grüezi',
)

# ── Status Overview ───────────────────────────────────────────────────────────
_STATUS_TOKENS: frozenset[str] = frozenset({'status'})
_STATUS_PHRASES: tuple[str, ...] = (
    'aktueller stand',
    'wie ist der stand',
    'was ist der stand',
    'wie laeuft',
    'was ist mit meinem fall',
    'mein letzter eingang',
    'update bitte',
    'neuigkeiten',
    'was passiert',
    'wie geht es meinem',
    'was liegt an',
    'was steht an',
    'was gibt es neues',
    'was gibts neues',
    'was gibts',
    'was gibt es',
    'ueberblick',
    'überblick',
    'zusammenfassung',
    'was hab ich verpasst',
    'was ist passiert',
    'was tut sich',
    'was geht ab',
    'kurzes update',
)

# ── Needs from User ───────────────────────────────────────────────────────────
_NEEDS_PHRASES: tuple[str, ...] = (
    'was brauchst du noch',
    'was fehlt noch',
    'was fehlt',
    'was braucht ihr noch',
    'was erwartet ihr noch',
    'was ist der naechste schritt',
    'was ist der naechste',
    'naechster schritt',
    'was kommt als naechstes',
)

# ── Document Arrival Check ────────────────────────────────────────────────────
_DOC_ARRIVAL_PHRASES: tuple[str, ...] = (
    'ist das dokument angekommen',
    'ist mein dokument angekommen',
    'ist das bild da',
    'hat das geklappt',
    'ist das angekommen',
    'ist mein dokument da',
    'kam meine nachricht an',
    'ist es angekommen',
)

# ── Last Case Explanation ─────────────────────────────────────────────────────
_CASE_EXPLANATION_PHRASES: tuple[str, ...] = (
    'worum geht es bei meinem fall',
    'erklaer mir das',
    'was ist mein fall',
    'was ist mein vorgang',
    'was wird bei mir bearbeitet',
    'was bearbeitest du fuer mich',
    'letzte rechnung',
    'letzter beleg',
    'letztes dokument',
    'was war die letzte rechnung',
    'was war das letzte',
    'zeig mir die letzte',
    'was kam zuletzt',
    'letzter vorgang',
    'was ist mit der rechnung',
    'warum ist er noch nicht',
    'warum ist sie noch nicht',
    'warum wurde das noch nicht',
    'warum nicht geprueft',
    'warum nicht geprüft',
    'noch nicht verarbeitet',
)

# ── Financial Query ───────────────────────────────────────────────────────────
_FINANCIAL_QUERY_PHRASES: tuple[str, ...] = (
    'wie viel hab ich', 'wie viel habe ich',
    'ausgaben diesen monat', 'ausgaben diese woche', 'monatliche ausgaben',
    'offene rechnungen', 'offene posten', 'was schuldet mir',
    'was schulde ich', 'kontostand', 'einnahmen',
    'was steht offen', 'ausstehende zahlungen',
    'unbezahlte rechnungen', 'forderungen', 'verbindlichkeiten',
)

# ── Create Invoice ───────────────────────────────────────────────────────────
_CREATE_INVOICE_PHRASES: tuple[str, ...] = (
    'erstelle eine rechnung', 'rechnung erstellen', 'rechnung schreiben',
    'schreib eine rechnung', 'neue rechnung', 'ausgangsrechnung erstellen',
    'rechnung an', 'fakturiere', 'invoice erstellen',
)

# ── Booking Request ──────────────────────────────────────────────────────────
_BOOKING_REQUEST_PHRASES: tuple[str, ...] = (
    'bitte buchen', 'kannst du das buchen', 'buchung durchfuehren',
    'diesen beleg buchen', 'rechnung buchen', 'verbuchen',
    'buchungsvorschlag', 'buchung erstellen',
)

# ── Export Request ───────────────────────────────────────────────────────────
_EXPORT_REQUEST_PHRASES: tuple[str, ...] = (
    'datev export', 'datev-export', 'exportiere',
    'daten exportieren', 'buchungen exportieren', 'fuer den steuerberater',
    'steuerberater export', 'gdpdu', 'betriebspruefung',
)

# ── Reminder Personal ────────────────────────────────────────────────────────
_REMINDER_PERSONAL_PHRASES: tuple[str, ...] = (
    'erinnere mich',
    'erinnerung',
    'remind me',
    'vergiss nicht',
    'nicht vergessen',
    'denk dran',
    'denke daran',
    'merk dir',
    'merke dir',
)

# ── Reminder Request ─────────────────────────────────────────────────────────
_REMINDER_REQUEST_PHRASES: tuple[str, ...] = (
    'erinnerung setzen', 'frist setzen',
    'deadline setzen', 'erinnere mich an',
)

# ── Create Customer ──────────────────────────────────────────────────────────
_CREATE_CUSTOMER_PHRASES: tuple[str, ...] = (
    'kunden anlegen', 'neuen kunden', 'kunde anlegen',
    'kontakt anlegen', 'lieferant anlegen', 'firma anlegen',
    'leg mal an', 'neuer kontakt', 'neuer lieferant',
    'als kunden an', 'als lieferant an',
)

# ── General Safe Help ─────────────────────────────────────────────────────────
_SAFE_HELP_PHRASES: tuple[str, ...] = (
    'was kannst du',
    'was macht frya',
    'wie funktioniert das',
    'kannst du mir helfen',
    'was kann frya',
    'wie kann ich',
    'was kannst du alles',
    'wie funktionierst du',
    'erklaer mir',
    'erklär mir',
    'erklaer mal',
    'erklär mal',
    'wie geht das',
    'anleitung',
)


def classify_intent(text: str) -> CommunicatorIntentCode | None:
    """Classify text into a communicator intent.

    Returns None for unrecognized text (fall-through to operator inbox).
    UNSUPPORTED_OR_RISKY overrides all other patterns.
    """
    t = text.strip().lower()
    if not t:
        return None

    # 0. REMINDER_PERSONAL — checked BEFORE risky to allow "Erinnere mich an Rechnung bezahlen"
    for phrase in _REMINDER_PERSONAL_PHRASES:
        if phrase in t:
            return 'REMINDER_PERSONAL'

    # 1. Risky check — overrides everything else
    for sub in _RISKY_SUBSTRINGS:
        if sub in t:
            return 'UNSUPPORTED_OR_RISKY'

    # 2. GREETING (single token or phrase) — use word-level match to avoid
    #    false positives like 'hi' in 'hier'.
    words = set(t.split())
    for token in _GREETING_TOKENS:
        if token in words:
            return 'GREETING'
    for phrase in _GREETING_PHRASES:
        if phrase in t:
            return 'GREETING'

    # 3. STATUS_OVERVIEW
    if t in _STATUS_TOKENS:
        return 'STATUS_OVERVIEW'
    for phrase in _STATUS_PHRASES:
        if phrase in t:
            return 'STATUS_OVERVIEW'

    # 4. NEEDS_FROM_USER
    for phrase in _NEEDS_PHRASES:
        if phrase in t:
            return 'NEEDS_FROM_USER'

    # 5. DOCUMENT_ARRIVAL_CHECK
    for phrase in _DOC_ARRIVAL_PHRASES:
        if phrase in t:
            return 'DOCUMENT_ARRIVAL_CHECK'

    # 6. LAST_CASE_EXPLANATION
    for phrase in _CASE_EXPLANATION_PHRASES:
        if phrase in t:
            return 'LAST_CASE_EXPLANATION'

    # 7. FINANCIAL_QUERY
    for phrase in _FINANCIAL_QUERY_PHRASES:
        if phrase in t:
            return 'FINANCIAL_QUERY'

    # 8. CREATE_INVOICE
    for phrase in _CREATE_INVOICE_PHRASES:
        if phrase in t:
            return 'CREATE_INVOICE'

    # 9. BOOKING_REQUEST
    for phrase in _BOOKING_REQUEST_PHRASES:
        if phrase in t:
            return 'BOOKING_REQUEST'

    # 10. EXPORT_REQUEST
    for phrase in _EXPORT_REQUEST_PHRASES:
        if phrase in t:
            return 'EXPORT_REQUEST'

    # 11b. REMINDER_REQUEST
    for phrase in _REMINDER_REQUEST_PHRASES:
        if phrase in t:
            return 'REMINDER_REQUEST'

    # 12. CREATE_CUSTOMER
    for phrase in _CREATE_CUSTOMER_PHRASES:
        if phrase in t:
            return 'CREATE_CUSTOMER'

    # 13. GENERAL_SAFE_HELP
    for phrase in _SAFE_HELP_PHRASES:
        if phrase in t:
            return 'GENERAL_SAFE_HELP'

    # 14. GENERAL_CONVERSATION — catch-all for any non-risky unrecognized text
    return 'GENERAL_CONVERSATION'
