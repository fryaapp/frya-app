"""Shared Chat-Logik die von REST und WebSocket aufgerufen wird.
Wird schrittweise befuellt — erst Pending, dann Shortcircuit, dann Orchestrator.

REGEL: Diese Datei ERSETZT customer_api.py und chat_ws.py NICHT.
Sie wird von beiden AUFGERUFEN.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Any

logger = logging.getLogger(__name__)

_DEFAULT_SUGGESTIONS = ['Inbox', 'Finanzen', 'Belege']

# ============================================================
# Communicator-Text fuer Daten-Intents (Sprint-02-06)
# Statt statischem "X Belege warten" → LLM formuliert menschlichen Text
# ============================================================

_DATA_TEXT_PROMPT = """\
Du bist Frya, eine warme und kompetente Buchhaltungs-Kollegin.
Der User hat gerade Daten abgefragt die als Karten/Charts angezeigt werden.
Formuliere einen KURZEN begleitenden Text (2-3 Saetze, Deutsch, per du).

REGELN:
- NICHT die Zahlen nochmal auflisten — die sieht der User in den Karten/Charts
- Stattdessen: EINORDNEN, KOMMENTIEREN, nächsten Schritt vorschlagen
- Wenn der User "Moin" oder "Hallo" gesagt hat: Grüße ZUERST zurück
- Wenn negativ (Verlust, überfällig): Ehrlich aber ermutigend
- Wenn positiv (Gewinn, alles erledigt): Anerkennung ohne Übertreibung
- KEIN "öffne die App", kein "/status", keine Slash-Befehle
- KEINE Emojis (ausser der User nutzt welche)
- Beginne NICHT mit "FRYA:"

DATEN:
Intent: {intent}
Zusammenfassung: {summary}

Letzte User-Nachricht: "{user_message}"

Formuliere den begleitenden Text:"""


async def _format_data_text(intent: str, data: dict, user_message: str) -> Optional[str]:
    """LLM-generierter Text fuer Daten-Intents. Timeout 3s, Fallback None."""
    import asyncio
    try:
        summary_parts = []
        if data.get('count') is not None:
            summary_parts.append(f"Anzahl: {data['count']}")
        if data.get('items'):
            vendors = [it.get('vendor', it.get('name', '')) for it in data['items'][:3] if isinstance(it, dict)]
            if vendors:
                summary_parts.append(f"Erste: {', '.join(v for v in vendors if v)}")
        if data.get('total_income') is not None:
            summary_parts.append(f"Einnahmen: {data['total_income']}€")
        if data.get('total_expenses') is not None:
            summary_parts.append(f"Ausgaben: {data['total_expenses']}€")
        if data.get('profit') is not None:
            summary_parts.append(f"Ergebnis: {data['profit']}€")
        if data.get('booking_count') is not None:
            summary_parts.append(f"Buchungen: {data['booking_count']}")
        summary = ', '.join(summary_parts) if summary_parts else str(data)[:200]

        prompt = _DATA_TEXT_PROMPT.format(
            intent=intent,
            summary=summary,
            user_message=user_message[:100],
        )

        from app.agents.tiered_orchestrator import TieredOrchestrator
        _orch = TieredOrchestrator()
        # Nutze 'orchestrator_router' (Llama 3.3 70B auf IONOS, ~2.4s warm) fuer Fallback-Text
        # Wird nur genutzt wenn generate_data_response() fehlschlaegt (Timeout/Exception)
        config = await _orch._get_llm_config('orchestrator_router')
        if not config or not config.get('full_model'):
            return None

        import litellm
        _call_kwargs = {
            'model': config['full_model'],
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 150,
            'temperature': 0.7,
        }
        # Bedrock nutzt AWS env vars, kein api_key. Andere Provider brauchen api_key.
        if config.get('api_key'):
            _call_kwargs['api_key'] = config['api_key']
        if config.get('base_url'):
            _call_kwargs['api_base'] = config['base_url']

        resp = await asyncio.wait_for(
            litellm.acompletion(**_call_kwargs),
            timeout=8.0,
        )
        text = (resp.choices[0].message.content or '').strip()
        # Strip "FRYA: " prefix if present
        text = re.sub(r'^FRYA:\s*', '', text)
        if text:
            logger.info('format_data_text OK: %s', text[:60])
            return text
    except asyncio.TimeoutError:
        logger.warning('format_data_text: Timeout (8s) — Fallback auf statischen Text')
    except Exception as exc:
        logger.warning('format_data_text: %s — Fallback auf statischen Text', exc)
    return None


async def get_history_messages(chat_id: str, max_messages: int = 10) -> list:
    """Sprint-03-03: Laedt Chat-History als messages-Array fuer LLM-Calls.

    Gibt eine Liste von {role, content}-Dicts zurueck.
    Genau wie die OpenAI/Anthropic Messages API es erwartet.
    """
    try:
        from app.dependencies import get_chat_history_store
        hist_store = get_chat_history_store()
        history = await hist_store.load(chat_id)
        recent = history[-max_messages:]
        messages = []
        for msg in recent:
            content = msg.get('content', '')
            if content and content.strip():
                messages.append({
                    'role': msg['role'],
                    'content': content,
                })
        return messages
    except Exception as exc:
        logger.debug('get_history_messages failed for %s: %s', chat_id, exc)
        return []


# ============================================================
# Sprint-04: Sonnet für Text + Suggestions (Llama nur noch Intent-Classify)
# Modell: Claude Sonnet 4.6 via AWS Bedrock (communicator-Slot)
# Llama 3.3 70B (orchestrator_router) macht NUR noch Intent-Classify — KEIN Text mehr
# ============================================================

# Sprint-04: Sonnet-Prompt für Daten-Intents. Ein Call, ein JSON-Output.
_SONNET_DATA_RESPONSE_SYSTEM_PROMPT = """Du bist Frya, eine digitale Kollegin für Buchhaltung.
Der User hat Daten abgefragt. Die Daten werden als Karten und Charts angezeigt.

DEINE AUFGABE — antworte als JSON:
{"text": "Dein Text (2-3 Sätze)", "suggestions": ["Vorschlag 1", "Vorschlag 2", "Vorschlag 3"]}

TEXT-REGELN:
- MAXIMAL 2-3 Sätze. Kurz und konkret.
- Nenne die WICHTIGSTEN Zahlen und Namen aus den Daten.
- Kommentiere: Was fällt auf? Was ist dringend? Was ist gut?
- KEINE leeren Phrasen: Nicht "Lass uns gemeinsam...", nicht "Das gibt dir eine gute Übersicht..."
- KEIN Lebenscoaching. Du bist Buchhalterin, nicht Therapeutin.
- Wenn Verlust: Sachlich. "502€ Minus — liegt an den Serverkosten."
- Wenn Gewinn: Kurz anerkennend. "Sieht gut aus, 340€ Plus."
- Begrüßung ("Moin!") NUR wenn keine vorherigen Messages im Chat-Verlauf.
- Sprich wie eine Kollegin die kurz was nachgeschaut hat.

SUGGESTION-REGELN:
- 2-4 kurze Sätze die der User als nächstes klicken könnte.
- JEDER Vorschlag muss SPEZIFISCH zum Kontext passen.
- Nutze konkrete Namen und Firmen aus den Daten.
- Mindestens 1 logischer nächster Schritt.

NUR DIESE FEATURES EXISTIEREN (nichts anderes vorschlagen):
- Inbox / Belege bearbeiten / freigeben
- Finanzen / EÜR
- Buchungen / Journal
- Kontakte
- Fristen
- Offene Posten / Mahnungen
- Rechnungen erstellen / ändern / versenden
- DATEV-Export / EÜR als PDF

NIEMALS vorschlagen: Umsatzprognosen, Einnahmen generieren, Steuerberatung, Konten abgleichen.

BEISPIELE:

Daten: Inbox 10 Belege, Hetzner und Finanzamt dringend
{"text": "10 Belege in der Inbox. Hetzner kenn ich — schnell abnicken. Finanzamt würde ich zuerst anschauen.", "suggestions": ["Finanzamt zuerst", "Alle durchgehen", "Hetzner freigeben"]}

Daten: Finanzen, 0€ Einnahmen, 1.963€ Ausgaben, -1.963€ Ergebnis
{"text": "1.963€ Ausgaben, noch keine Einnahmen verbucht. Hast du offene Rechnungen draußen?", "suggestions": ["Offene Rechnungen prüfen", "Größte Ausgabenposten", "EÜR als PDF"]}

Daten: 3 offene Posten, Weber 285€ überfällig
{"text": "Drei offene Posten. Weber ist 14 Tage überfällig — 285€.", "suggestions": ["Weber mahnen", "Alle Posten anzeigen", "Gesamtsumme?"]}"""

# DEPRECATED (Sprint-04): Nicht mehr aufgerufen. Bleibt für Rückwärtskompatibilität.
_LLAMA_DATA_RESPONSE_SYSTEM_PROMPT = _SONNET_DATA_RESPONSE_SYSTEM_PROMPT


# DEPRECATED (Sprint-03-03): Wird nicht mehr aufgerufen. Bleibt fuer Rueckwaertskompatibilitaet.
# History kommt jetzt als messages-Array, kein format_for_llm() + chat_context_block mehr.
_LLAMA_DATA_RESPONSE_PROMPT = """\
Du bist Frya, eine digitale Kollegin für Buchhaltung.
Der User hat gerade Daten abgefragt. Du siehst die Daten unten.

KONVERSATIONS-POSITION: {conversation_position}
STIMMUNG DER DATEN: {sentiment}

{chat_context_block}

DEINE AUFGABE:
1. Schreib einen KURZEN begleitenden Text (2-3 Sätze)
   - Kommentiere die Daten, ordne sie ein, gib einen Tipp
   - Die Daten werden bereits als Karten/Charts angezeigt — NICHT nochmal auflisten
   - Wenn ERSTE_NACHRICHT: Kurze Begrüssung erlaubt ("Moin!", "Hey!")
   - Wenn MITTE_DES_GESPRÄCHS: KEINE Begrüssung. Direkt zum Punkt.
   - "Läuft bei dir!" NUR wenn SENTIMENT = POSITIV
   - LEICHT_NEGATIV: Sachlich ("Kleines Minus diesen Monat — liegt an den Ausgaben")
   - STARK_NEGATIV: Ernst ("Da müssen wir aufpassen — die Ausgaben sind zu hoch")
   - KEINE_EINNAHMEN: "Noch keine Einnahmen verbucht — hast du offene Rechnungen?"
   - NIEMALS widersprüchliche Aussagen (kein "Läuft bei dir!" bei Verlust)

2. Schlage 3 SPEZIFISCHE nächste Schritte vor (klickbare Buttons)
   - Nutze konkrete Namen, Beträge, Firmen aus den Daten
   - Formuliere als natürliche Sätze

FRYA KANN (NUR diese Kategorien in Suggestions anbieten):
- Inbox anzeigen / Belege anschauen / einzelnen Beleg nach Firmenname
- Finanzen / EÜR / Einnahmen vs. Ausgaben
- Buchungen anzeigen / Buchungsjournal
- Kontakte anzeigen / suchen
- Fristen anzeigen
- Offene Posten / Mahnung schreiben / Forderungen
- Rechnungen erstellen / ändern / versenden
- Belege freigeben / ablehnen / korrigieren
- DATEV-Export / EÜR als PDF

WICHTIG: Verwende IMMER echte deutsche Umlaute (ä, ö, ü) — NIEMALS ae, oe, ue schreiben!

FRYA KANN NICHT (NIEMALS in Suggestions anbieten):
- Umsatzprognose / Umsatz steigern / Einnahmen generieren
- Steueroptimierung / Steuerberatung
- Konten abgleichen / Kontenrahmen
- Automatische Zahlungen / Bankverbindungen
- Irgendwas das kein reales FRYA-Feature ist

BEISPIELE:

Erste Nachricht, SHOW_INBOX, 10 Belege, Finanzamt dringend, NEUTRAL:
{{"text": "Moin! 10 Belege in der Inbox — das Finanzamt würde ich zuerst anschauen.", "suggestions": ["Finanzamt zuerst", "Alle durchgehen", "Nur die dringenden"]}}

Mitte des Gesprächs, SHOW_FINANCE, -502 EUR (LEICHT_NEGATIV):
{{"text": "Kleines Minus diesen Monat — 502 Euro mehr raus als rein.", "suggestions": ["Wo gebe ich am meisten aus?", "EÜR als PDF", "Offene Rechnungen prüfen"]}}

Mitte, SHOW_FINANCE, +1200 EUR (POSITIV):
{{"text": "Im Plus! 1200 Euro Gewinn diesen Monat.", "suggestions": ["EÜR als PDF", "Offene Rechnungen prüfen", "Buchungen anzeigen"]}}

Mitte, SHOW_OPEN_ITEMS, Weber 285 EUR überfällig 14 Tage, LEICHT_NEGATIV:
{{"text": "Drei offene Posten — Weber wartet am längsten, 285 Euro seit zwei Wochen.", "suggestions": ["Weber eine Mahnung schreiben", "Alle offenen Posten anzeigen", "Gesamtsumme prüfen"]}}

JETZT:

Intent: {intent}
Daten: {data_summary}
Dringende Items: {urgent_items}
Letzte User-Nachricht: "{user_message}"

Antworte NUR als JSON (kein Markdown, kein Text drumherum):
{{"text": "...", "suggestions": ["...", "...", "..."]}}"""


def _extract_summary(data: dict) -> dict:
    """Extrahiert kompakte Kennzahlen fuer Llama Data-Prompt."""
    if not isinstance(data, dict):
        return {}
    summary: dict = {}

    # Anzahl
    if data.get('count') is not None:
        summary['anzahl'] = data['count']
    elif 'items' in data:
        summary['anzahl'] = len(data['items'])

    # Top-Items (Namen + Betraege, max 5)
    items = data.get('items', data.get('bookings', data.get('contacts', [])))
    if items and isinstance(items, list):
        summary['top_items'] = [
            {
                'name': item.get('vendor', item.get('name', item.get('correspondent', '?'))),
                'amount': item.get('amount', item.get('betrag', '')),
                'status': item.get('status', item.get('priority', '')),
            }
            for item in items[:5]
            if isinstance(item, dict)
        ]

    # Finanzen
    for key in ('total_income', 'total_expenses', 'profit', 'booking_count'):
        if data.get(key) is not None:
            summary[key] = data[key]

    # Offene Posten
    if 'overdue' in data:
        overdue = data['overdue']
        summary['ueberfaellig'] = len(overdue) if isinstance(overdue, list) else overdue

    return summary


def _determine_sentiment(data: dict) -> str:
    """Bestimmt ob die Daten positiv/negativ/neutral sind fuer Ton-Steuerung."""
    if not isinstance(data, dict):
        return 'NEUTRAL'
    result = data.get('profit', data.get('result'))
    if result is not None:
        try:
            v = float(result)
            if v > 0:
                return 'POSITIV'
            if v < -500:
                return 'STARK_NEGATIV'
            if v < 0:
                return 'LEICHT_NEGATIV'
        except (TypeError, ValueError):
            pass
    income = float(data.get('total_income', data.get('income', data.get('einnahmen', 0))) or 0)
    expenses = float(data.get('total_expenses', data.get('expenses', data.get('ausgaben', 0))) or 0)
    if income == 0 and expenses > 0:
        return 'KEINE_EINNAHMEN'
    return 'NEUTRAL'


import re as _re_sugg

_KNOWN_SUGGESTION_PATTERNS = [
    r'inbox|belege?|posteingang|dokument',
    r'finanz|euer|einnahmen?|ausgaben?|buchhaltu',
    r'buchung(en)?|journal|kontobewegung',
    r'kontakt|kunden?|lieferant',
    r'frist(en)?|deadline|f\u00e4llig|termin',
    r'offen(e)?.*posten|schuld|mahnung|forderung',
    r'rechnung(en)?|faktur',
    r'freigeb|genehmig|ablehnen|korrigier',
    r'export|datev|pdf',
    r'beleg|vorgang',
    r'anzeigen?|zeig|pr[uü]fen|durchgehen',
]


def validate_suggestions(suggestions: list, service_data: dict = None) -> list:
    """Entfernt Suggestions die FRYA nicht ausfuehren kann (Halluzinationen).

    Behaelt Suggestions die einem bekannten FRYA-Feature-Pattern entsprechen
    ODER einen konkreten Firmennamen aus den aktuellen Daten enthalten.
    """
    if not suggestions:
        return ['Inbox anzeigen', 'Wie stehen die Finanzen?', 'Offene Posten prüfen']

    # Firmennamen aus den aktuellen Service-Daten sind immer erlaubt
    known_names: set = set()
    if service_data and isinstance(service_data, dict):
        for item in service_data.get('items', service_data.get('overdue', [])):
            if isinstance(item, dict):
                name = item.get('vendor', item.get('name', item.get('correspondent', '')))
                if name:
                    known_names.add(name.lower())

    valid = []
    for sugg in suggestions:
        text = (sugg or '').lower()
        matches_pattern = any(_re_sugg.search(p, text) for p in _KNOWN_SUGGESTION_PATTERNS)
        matches_name = any(name in text for name in known_names if len(name) >= 4)
        if matches_pattern or matches_name:
            valid.append(sugg)
        else:
            logger.info("Suggestion gefiltert (unbekanntes Feature): '%s'", sugg)

    if not valid:
        valid = ['Inbox anzeigen', 'Wie stehen die Finanzen?', 'Offene Posten prüfen']

    return valid[:4]


def _build_context_summary(intent: str, data: dict) -> dict:
    """Baut eine kompakte Zusammenfassung der Service-Daten fuer die Chat-History.

    Maximal ~500 Zeichen — nicht die kompletten Rohdaten.
    Wird als context_data in ChatHistoryStore gespeichert.
    """
    if not isinstance(data, dict):
        return {'intent': intent}
    summary: dict = {'intent': intent}

    items = data.get('items', data.get('bookings', data.get('contacts', data.get('overdue', []))))
    if items and isinstance(items, list):
        key_items = []
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            name = item.get('vendor', item.get('name', item.get('correspondent', '?')))
            amount = item.get('amount', item.get('betrag', ''))
            status = item.get('status', '')
            if amount:
                key_items.append(f'{name} {amount}€ {status}'.strip())
            else:
                key_items.append(f'{name} {status}'.strip())
        summary['items'] = key_items
        summary['count'] = len(items)

    for key in ('total_income', 'total_expenses', 'profit', 'booking_count',
                'income', 'expenses', 'result'):
        if data.get(key) is not None:
            summary[key] = data[key]

    return summary


def _get_urgent(data: dict) -> list:
    """Extrahiert dringende Items damit Llama sie konkret in Suggestions nennen kann."""
    if not isinstance(data, dict):
        return []
    urgent = []
    for item in data.get('items', data.get('overdue', [])):
        if isinstance(item, dict):
            is_urgent = (
                item.get('priority') in ('HIGH', 'URGENT') or
                item.get('overdue') is True or
                item.get('status') in ('OVERDUE', 'ueberfaellig', 'overdue')
            )
            if is_urgent:
                urgent.append({
                    'name': item.get('vendor', item.get('name', '')),
                    'amount': item.get('amount', ''),
                })
    return urgent[:3]


async def generate_data_response(
    intent: str,
    data: dict,
    user_message: str,
    chat_id: str = None,
    # DEPRECATED (Sprint-03-03): chat_history und is_first_message werden ignoriert.
    # History kommt jetzt als messages-Array via chat_id.
    chat_history: list = None,
    is_first_message: bool = True,
) -> dict:
    """Sprint-04: Claude Sonnet 4.6 generiert Text + Suggestions fuer Daten-Intents.

    Llama 3.3 70B macht NUR noch Intent-Classify. Sonnet übernimmt Text-Generierung.
    Timeout 12s. Bei Fehler: {'text': None, 'suggestions': []} → Caller nutzt Fallback.
    Nutzt 'communicator' Slot (Claude Sonnet 4.6 via AWS Bedrock).

    Sprint-03-03: History als echtes messages-Array (ChatGPT-Stil).
    - chat_id: Chat-ID fuer Redis-History-Laden
    - System-Prompt = _SONNET_DATA_RESPONSE_SYSTEM_PROMPT
    - History = letzte 10 Nachrichten aus Redis
    - User-Message = Intent + Daten-Summary
    """
    import asyncio
    import json as _json

    try:
        summary = _extract_summary(data)
        urgent = _get_urgent(data)

        # Sprint-03-03: History aus Redis als messages-Array
        history_msgs: list = []
        if chat_id:
            history_msgs = await get_history_messages(chat_id, max_messages=10)

        messages = [
            {'role': 'system', 'content': _SONNET_DATA_RESPONSE_SYSTEM_PROMPT},
            *history_msgs,
            {'role': 'user', 'content': (
                f"Intent: {intent}\n"
                f"Daten: {_json.dumps(summary, ensure_ascii=False, default=str)}\n"
                f"Dringende Items: {_json.dumps(urgent, ensure_ascii=False, default=str) if urgent else 'Keine'}"
            )},
        ]

        import litellm, os as _os
        # Sprint-04: Sonnet direkt via Anthropic API (FRYA_ANTHROPIC_API_KEY)
        # Bedrock-Slot hat kein api_key → direkt Anthropic-API nutzen (getestet: claude-sonnet-4-5 OK)
        _anthropic_key = _os.environ.get('FRYA_ANTHROPIC_API_KEY') or _os.environ.get('ANTHROPIC_API_KEY')
        if not _anthropic_key:
            # Fallback auf orchestrator_router (Llama) wenn kein Anthropic-Key
            logger.warning('generate_data_response: kein Anthropic-Key, versuche Llama-Fallback')
            from app.agents.tiered_orchestrator import TieredOrchestrator
            _orch = TieredOrchestrator()
            config = await _orch._get_llm_config('orchestrator_router')
            if not config or not config.get('api_key'):
                return {'text': None, 'suggestions': []}
            resp = await asyncio.wait_for(
                litellm.acompletion(
                    model=config['full_model'],
                    messages=messages,
                    max_tokens=250,
                    temperature=0.7,
                    api_key=config['api_key'],
                    api_base=config.get('base_url'),
                ),
                timeout=8.0,
            )
        else:
            resp = await asyncio.wait_for(
                litellm.acompletion(
                    model='anthropic/claude-sonnet-4-5',
                    messages=messages,
                    max_tokens=250,
                    temperature=0.7,
                    api_key=_anthropic_key,
                ),
                timeout=12.0,  # 12s Timeout für Sonnet
            )

        raw = (resp.choices[0].message.content or '').strip()
        # Markdown-Code-Blocks entfernen falls Llama sie zurueckgibt
        if '```' in raw:
            raw = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', raw, flags=re.DOTALL).strip()

        parsed = _json.loads(raw)
        text = (parsed.get('text') or '').strip()
        # Strip "FRYA:" prefix falls vorhanden
        text = re.sub(r'^FRYA:\s*', '', text)
        suggestions = [str(s) for s in parsed.get('suggestions', [])[:3]]

        if text:
            # FIX 2: Suggestions validieren — nur existierende FRYA-Features
            validated_sugg = validate_suggestions(suggestions, data)
            logger.info('generate_data_response OK: %s | sugg=%s', text[:60], validated_sugg)
            return {'text': text, 'suggestions': validated_sugg}

        logger.warning('generate_data_response: leerer text in JSON | raw=%s', raw[:100])

    except asyncio.TimeoutError:
        logger.warning('generate_data_response: Timeout (8s) — Fallback auf Mistral+statisch')
    except Exception as exc:
        logger.warning('generate_data_response failed: %s', exc)

    return {'text': None, 'suggestions': []}


# ============================================================
# Confirmation / Rejection (Divergenz #6: WS hat mehr Woerter → WS-Version)
# ============================================================

CONFIRMATION_WORDS = frozenset({
    'ja', 'jo', 'jep', 'jap', 'jup', 'yes', 'ok', 'okay', 'oke',
    'genau', 'stimmt', 'richtig', 'korrekt', 'passt', 'perfekt',
    'mach', 'mach das', 'tu das', 'los', 'go', 'weiter',
    'ja bitte', 'ja genau', 'ja danke', 'ja mach', 'ja klar',
    'in ordnung', 'alles klar', 'einverstanden', 'gerne',
    'ja gerne', 'bitte', 'ja bitte mach das',
})

REJECTION_WORDS = frozenset({
    'nein', 'nee', 'ne', 'noe', 'nicht', 'stop', 'stopp',
    'abbrechen', 'cancel', 'lass', 'lass das', 'vergiss es',
    'doch nicht', 'lieber nicht', 'nein danke',
})

CANCEL_KEYWORDS = ('abbrech', 'vergiss', 'nein', 'stop', 'cancel',
                   'aufhoeren', 'nicht mehr', 'lass es', 'skip', 'ignorier')


def _is_confirmation(message: str) -> bool:
    return message.lower().strip().rstrip('.!?') in CONFIRMATION_WORDS


def _is_rejection(message: str) -> bool:
    return message.lower().strip().rstrip('.!?') in REJECTION_WORDS


def _is_cancel(message: str) -> bool:
    return any(kw in message.lower() for kw in CANCEL_KEYWORDS)


# ============================================================
# SCHRITT 1: PENDING-CHECKS
# ============================================================

async def check_and_handle_pending(
    message: str,
    tenant_id: str,
    user_id: str,
    chat_id: str,
    pending_flow: Optional[dict] = None,
) -> Optional[dict]:
    """Prueft ob ein Pending-State existiert und verarbeitet die Message.

    Args:
        message: User-Nachricht
        tenant_id: Tenant-ID (aus JWT)
        user_id: User-ID (aus JWT sub)
        chat_id: Chat-ID fuer Redis-Keys (z.B. 'web-testkunde')
        pending_flow: WS-only Pending-Flow (websocket._frya_pending_flow)

    Returns:
        dict mit Response-Daten wenn ein Pending verarbeitet wurde.
            Enthaelt immer: text, content_blocks, actions, routing, case_ref, context_type, suggestions
            Optional: next_pending_flow (neuer Pending-Flow-Zustand fuer WS)
        None wenn kein Pending gefunden → Caller macht normal weiter.
    """
    # Reihenfolge: pending_flow → pending_invoice → pending_action
    # (pending_flow hat Prioritaet weil es einen aktiven Multi-Step-Flow bedeutet)

    # 1. pending_flow (WS-only, wird als Parameter reingegeben)
    if pending_flow and isinstance(pending_flow, dict):
        result = await _handle_pending_flow(message, pending_flow, user_id, tenant_id)
        if result is not None:
            return result

    # 2. pending_invoice (Redis — Divergenz #8: Redis ueberlebt Reconnect)
    try:
        invoice_result = await _handle_pending_invoice(message, user_id, tenant_id, chat_id)
        if invoice_result is not None:
            return invoice_result
    except Exception as exc:
        # REGEL P3: Redis non-blocking
        logger.warning('Pending-invoice check failed: %s', exc)

    # 3. pending_action (Redis)
    try:
        action_result = await _handle_pending_action(message, tenant_id, user_id)
        if action_result is not None:
            return action_result
    except Exception as exc:
        # REGEL P3: Redis non-blocking
        logger.warning('Pending-action check failed: %s', exc)

    return None


# ============================================================
# pending_flow Handler (kopiert aus chat_ws.py Zeilen 936-1136)
# ============================================================

async def _handle_pending_flow(
    message: str, pending_flow: dict, user_id: str, tenant_id: str,
) -> Optional[dict]:
    """Verarbeitet einen laufenden Multi-Step-Flow."""
    _pf_type = pending_flow.get('waiting_for')
    _pf_invoice_id = pending_flow.get('invoice_id')
    _pf_data = pending_flow.get('pending_data', {})

    # Cancel-Check
    if _is_cancel(message):
        return {
            'text': 'Alles klar, ich habe den Vorgang abgebrochen. Was kann ich sonst fuer dich tun?',
            'case_ref': None,
            'context_type': 'none',
            'suggestions': _DEFAULT_SUGGESTIONS,
            'content_blocks': [],
            'actions': [],
            'routing': 'cancel',
            'next_pending_flow': None,  # Clear pending
        }

    # --- recipient_email ---
    if _pf_type == 'recipient_email' and _pf_invoice_id:
        from app.services.invoice_pipeline import handle_send_invoice
        _send_result = await handle_send_invoice(
            {'invoice_id': _pf_invoice_id, 'recipient_email': message.strip()},
            user_id, tenant_id=tenant_id,
        )
        return {
            'text': _send_result.get('text', ''),
            'case_ref': None,
            'context_type': 'none',
            'suggestions': [a['chat_text'] for a in _send_result.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
            'content_blocks': _send_result.get('content_blocks', []),
            'actions': _send_result.get('actions', []),
            'routing': 'pending_flow',
            'next_pending_flow': None,
        }

    # --- company_profile_wizard ---
    if _pf_type == 'company_profile_wizard' and _pf_data:
        from app.api.chat_ws import _extract_and_persist_business_info
        await _extract_and_persist_business_info(message, user_id, tenant_id)
        from app.services.invoice_pipeline import handle_create_invoice
        _cpw_result = await handle_create_invoice(_pf_data, user_id, tenant_id=tenant_id)
        # Determine next pending flow
        next_pf = None
        if _cpw_result.get('_waiting_for') == 'company_profile_wizard':
            next_pf = {
                'waiting_for': 'company_profile_wizard',
                'pending_data': _cpw_result.get('_pending_data', _pf_data),
            }
        elif _cpw_result.get('awaiting_email_for_invoice'):
            next_pf = {
                'waiting_for': 'recipient_email',
                'invoice_id': _cpw_result['awaiting_email_for_invoice'],
                'pending_data': _pf_data,
            }
        return {
            'text': _cpw_result.get('text', ''),
            'case_ref': None,
            'context_type': _cpw_result.get('context_type', 'none'),
            'suggestions': [a['chat_text'] for a in _cpw_result.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
            'content_blocks': _cpw_result.get('content_blocks', []),
            'actions': _cpw_result.get('actions', []),
            'routing': 'pending_flow',
            'next_pending_flow': next_pf,
        }

    # --- recipient_address ---
    if _pf_type == 'recipient_address' and _pf_data:
        _pf_data['contact_address'] = message.strip()
        from app.services.invoice_pipeline import handle_create_invoice
        _resume = await handle_create_invoice(_pf_data, user_id, tenant_id=tenant_id)
        next_pf = None
        if _resume.get('_pending_intent'):
            next_pf = {
                'waiting_for': 'recipient_address',
                'pending_data': _resume.get('_pending_data', _pf_data),
            }
        return {
            'text': _resume.get('text', ''),
            'case_ref': None,
            'context_type': _resume.get('context_type', 'invoice_draft'),
            'suggestions': [a['chat_text'] for a in _resume.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
            'content_blocks': _resume.get('content_blocks', []),
            'actions': _resume.get('actions', []),
            'routing': 'pending_flow',
            'next_pending_flow': next_pf,
        }

    # --- invoice_draft_review (P-43 Fix B) ---
    if _pf_type == 'invoice_draft_review' and _pf_invoice_id:
        _inv_mod_patterns = [
            r'(?:aender|änder|change|mach).*(?:betrag|preis|summe|€|euro|\d)',
            r'(?:aender|änder).*(?:adresse|name|empfaenger|empfänger|beschreibung)',
            r'(?:statt|anstatt)\s*\d+',
            r'\d+\s*€?\s*(?:statt|anstatt|draus|daraus)',
            r'(?:betrag|preis|summe)\s*(?:auf|zu|soll|=)\s*\d+',
            r'(?:mach|setze?)\s*\d+\s*€?\s*(?:draus|daraus)',
            r'(?:fuege|füge|add|noch)\s+\d+\s+.+\s+(?:zu|à|a|@)\s*\d+',
            r'(?:andere?|neue?)\s*(?:adresse|beschreibung|position)',
        ]
        _is_mod = any(re.search(p, message.lower()) for p in _inv_mod_patterns)
        _is_send = any(kw in message.lower() for kw in ('freigeben', 'senden', 'verschicken', 'abschicken', 'sieht gut aus'))
        _is_void = any(kw in message.lower() for kw in ('verwerfen', 'loeschen', 'löschen', 'stornieren'))

        if _is_mod:
            from app.services.invoice_pipeline import handle_modify_invoice
            _mod = await handle_modify_invoice(_pf_invoice_id, message, user_id, tenant_id=tenant_id)
            _mod_inv_id = _mod.get('invoice_id', _pf_invoice_id)
            return {
                'text': _mod.get('text', ''),
                'case_ref': None,
                'context_type': 'invoice_draft',
                'suggestions': [a['chat_text'] for a in _mod.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                'content_blocks': _mod.get('content_blocks', []),
                'actions': _mod.get('actions', []),
                'routing': 'pending_flow',
                'next_pending_flow': {
                    'waiting_for': 'invoice_draft_review',
                    'invoice_id': _mod_inv_id,
                    'pending_data': _pf_data,
                },
            }
        elif _is_send:
            from app.services.invoice_pipeline import handle_send_invoice
            _send_r = await handle_send_invoice({'invoice_id': _pf_invoice_id}, user_id, tenant_id=tenant_id)
            next_pf = None
            if _send_r.get('awaiting_email_for_invoice'):
                next_pf = {
                    'waiting_for': 'recipient_email',
                    'invoice_id': _send_r['awaiting_email_for_invoice'],
                    'pending_data': _pf_data,
                }
            return {
                'text': _send_r.get('text', ''),
                'case_ref': None,
                'context_type': _send_r.get('context_type', 'none'),
                'suggestions': [a['chat_text'] for a in _send_r.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                'content_blocks': _send_r.get('content_blocks', []),
                'actions': _send_r.get('actions', []),
                'routing': 'pending_flow',
                'next_pending_flow': next_pf,
            }
        elif _is_void:
            from app.services.invoice_pipeline import handle_void_invoice
            _void_r = await handle_void_invoice({'invoice_id': _pf_invoice_id}, user_id)
            return {
                'text': _void_r.get('text', 'Rechnung verworfen.'),
                'case_ref': None,
                'context_type': 'none',
                'suggestions': _DEFAULT_SUGGESTIONS,
                'content_blocks': _void_r.get('content_blocks', []),
                'actions': _void_r.get('actions', []),
                'routing': 'pending_flow',
                'next_pending_flow': None,
            }
        else:
            # Unbekannte Nachricht im Rechnungs-Flow:
            # NICHT fallen lassen! Als Modifikation behandeln — der User
            # antwortet auf eine Flow-Frage (z.B. "Pauschalpreis" auf
            # "Stunden oder Pauschalpreis?"). An die Invoice Pipeline weiterleiten.
            try:
                from app.services.invoice_pipeline import handle_modify_invoice
                _fallback_mod = await handle_modify_invoice(_pf_invoice_id, message, user_id, tenant_id=tenant_id)
                _fb_inv_id = _fallback_mod.get('invoice_id', _pf_invoice_id)
                return {
                    'text': _fallback_mod.get('text', ''),
                    'case_ref': None,
                    'context_type': 'invoice_draft',
                    'suggestions': [a['chat_text'] for a in _fallback_mod.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                    'content_blocks': _fallback_mod.get('content_blocks', []),
                    'actions': _fallback_mod.get('actions', []),
                    'routing': 'pending_flow',
                    'next_pending_flow': {
                        'waiting_for': 'invoice_draft_review',
                        'invoice_id': _fb_inv_id,
                        'pending_data': _pf_data,
                    },
                }
            except Exception as _fb_exc:
                logger.warning('invoice_draft_review fallback failed: %s', _fb_exc)
                return None  # Nur bei echtem Fehler fallen lassen

    # Unknown pending_flow type — let caller handle normally
    return None


# ============================================================
# pending_invoice Handler (Redis — Divergenz #8: Redis > WS-Attribut)
# Kopiert aus customer_api.py Zeilen 149-204, ergaenzt mit WS-Patterns
# ============================================================

async def _handle_pending_invoice(
    message: str, user_id: str, tenant_id: str, chat_id: str,
) -> Optional[dict]:
    """Prueft Redis auf pending_invoice und verarbeitet Rechnungsaenderungen."""
    import redis.asyncio as aioredis
    from app.config import get_settings

    try:
        r = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        pi_key = f'frya:pending_invoice:{chat_id}'

        # REGEL P5: Atomischer GET (delete erst nach Verarbeitung)
        pi_raw = await r.get(pi_key)
        if not pi_raw:
            await r.aclose()
            return None

        pi_data = json.loads(pi_raw)
        pi_invoice_id = pi_data.get('invoice_id')
        if not pi_invoice_id:
            await r.aclose()
            return None

        # Patterns aus WS (vollstaendiger als REST)
        _inv_mod_patterns = [
            r'(?:aender|änder|change|mach).*(?:betrag|preis|summe|€|euro|\d)',
            r'(?:aender|änder).*(?:adresse|name|empfaenger|empfänger|beschreibung)',
            r'(?:statt|anstatt)\s*\d+',
            r'\d+\s*€?\s*(?:statt|anstatt|draus|daraus)',
            r'(?:betrag|preis|summe)\s*(?:auf|zu|soll|=)\s*\d+',
            r'(?:mach|setze?)\s*\d+\s*€?\s*(?:draus|daraus)',
            r'(?:fuege|füge|add|noch)\s+\d+\s+.+\s+(?:zu|à|a|@)\s*\d+',
            r'(?:andere?|neue?)\s*(?:adresse|beschreibung|position)',
        ]
        _is_mod = any(re.search(p, message.lower()) for p in _inv_mod_patterns)
        _is_send = any(kw in message.lower() for kw in ('freigeben', 'senden', 'verschicken', 'sieht gut aus'))
        _is_void = any(kw in message.lower() for kw in ('verwerfen', 'loeschen', 'löschen', 'stornieren'))

        if _is_mod:
            from app.services.invoice_pipeline import handle_modify_invoice
            _mod = await handle_modify_invoice(pi_invoice_id, message, user_id, tenant_id=tenant_id)
            _mod_inv_id = _mod.get('invoice_id', pi_invoice_id)
            # Update Redis with new invoice_id
            try:
                await r.set(pi_key, json.dumps({'invoice_id': _mod_inv_id, 'pending_data': pi_data.get('pending_data', {})}, ensure_ascii=False), ex=300)
            except Exception as redis_exc:
                logger.warning('Redis set after modify failed: %s', redis_exc)
            await r.aclose()
            return {
                'text': _mod.get('text', ''),
                'case_ref': None,
                'context_type': 'invoice_draft',
                'suggestions': [a['chat_text'] for a in _mod.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                'content_blocks': _mod.get('content_blocks', []),
                'actions': _mod.get('actions', []),
                'routing': 'pending_flow',
            }
        elif _is_send:
            try:
                await r.delete(pi_key)
            except Exception:
                pass
            await r.aclose()
            from app.services.invoice_pipeline import handle_send_invoice
            _send = await handle_send_invoice({'invoice_id': pi_invoice_id}, user_id, tenant_id=tenant_id)
            return {
                'text': _send.get('text', ''),
                'case_ref': None,
                'context_type': _send.get('context_type', 'none'),
                'suggestions': [a['chat_text'] for a in _send.get('actions', [])[:3]] or _DEFAULT_SUGGESTIONS,
                'content_blocks': _send.get('content_blocks', []),
                'actions': _send.get('actions', []),
                'routing': 'pending_flow',
            }
        elif _is_void:
            try:
                await r.delete(pi_key)
            except Exception:
                pass
            await r.aclose()
            from app.services.invoice_pipeline import handle_void_invoice
            _void = await handle_void_invoice({'invoice_id': pi_invoice_id}, user_id)
            return {
                'text': _void.get('text', 'Rechnung verworfen.'),
                'case_ref': None,
                'context_type': 'none',
                'suggestions': _DEFAULT_SUGGESTIONS,
                'content_blocks': _void.get('content_blocks', []),
                'actions': _void.get('actions', []),
                'routing': 'pending_flow',
            }

        await r.aclose()
    except Exception as exc:
        logger.warning('Pending-invoice Redis error: %s', exc)

    return None


# ============================================================
# pending_action Handler (Divergenz #7: WS differenziert Actions → WS-Version)
# Kopiert aus chat_ws.py Zeilen 1138-1211
# ============================================================

async def _handle_pending_action(
    message: str, tenant_id: str, user_id: str,
) -> Optional[dict]:
    """Prueft Redis auf pending_action und verarbeitet Ja/Nein.

    3 Faelle:
    1. _is_confirmation(message) → Action ausfuehren
    2. _is_rejection(message) → Action abbrechen
    3. Weder noch → return None (normal weiter, Pending BLEIBT)
    """
    cleaned = message.lower().strip().rstrip('.!?')
    is_confirm = cleaned in CONFIRMATION_WORDS
    is_reject = cleaned in REJECTION_WORDS

    if not is_confirm and not is_reject:
        # Fall 3: Weder Ja noch Nein → normal weiterarbeiten
        return None

    import redis.asyncio as aioredis
    from app.config import get_settings

    try:
        r = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        pa_key = f'frya:pending_action:{tenant_id or user_id}'

        # REGEL P5: Atomischer GET+DEL
        pipe = r.pipeline()
        pipe.get(pa_key)
        pipe.delete(pa_key)
        results = await pipe.execute()
        await r.aclose()

        pa_raw = results[0]
        deleted = results[1]

        if not pa_raw:
            return None  # Kein Pending → normal weiter

        if not deleted:
            return None  # Bereits von anderem Request verarbeitet (Doppelklick)

        pa_data = json.loads(pa_raw)

        if is_confirm:
            pa_action = pa_data.get('action')
            pa_case_ref = pa_data.get('case_ref')
            pa_params = pa_data.get('params', {})
            pa_confirm_text = pa_data.get('confirm_text', 'Erledigt.')

            # Differenzierte Action-Ausfuehrung (Divergenz #7: WS-Version)
            if pa_action == 'approve' and pa_case_ref:
                try:
                    from app.agents.service_registry import _InboxService
                    _inbox = _InboxService()
                    _ap_r = await _inbox.approve(case_id=pa_case_ref, tenant_id=tenant_id)
                    pa_confirm_text = _ap_r.get('text', 'Buchung freigegeben.')
                except Exception as approve_exc:
                    logger.warning('Pending-action approve failed: %s', approve_exc)
            elif pa_action == 'rebooking' and pa_case_ref:
                pa_confirm_text = f'Umbuchung auf {pa_params.get("new_account", "?")} durchgefuehrt.'

            return {
                'text': pa_confirm_text,
                'case_ref': pa_case_ref,
                'context_type': 'none',
                'suggestions': _DEFAULT_SUGGESTIONS,
                'content_blocks': [{'block_type': 'alert', 'data': {'severity': 'success', 'text': pa_confirm_text}}],
                'actions': [],
                'routing': 'pending_action',
            }
        else:
            # Rejection
            return {
                'text': 'Alles klar, abgebrochen. Was kann ich sonst fuer dich tun?',
                'case_ref': None,
                'context_type': 'none',
                'suggestions': _DEFAULT_SUGGESTIONS,
                'content_blocks': [],
                'actions': [],
                'routing': 'pending_action',
            }

    except Exception as exc:
        # REGEL P3: Redis non-blocking
        logger.warning('Pending-action Redis error: %s', exc)

    return None


# ============================================================
# SCHRITT 2B: SHORTCIRCUIT-VERARBEITUNG
# Kopiert aus chat_ws.py Zeilen 1341-1449
# KRITISCH: Chart-Logik + ResponseBuilder MUSS enthalten sein!
# ============================================================

from app.core.intents import Intent

# Intent → Service-Registry Mapping (aus WS — vollstaendiger als REST)
_CHART_SHORTCIRCUIT_INTENTS = frozenset({
    Intent.SHOW_FINANCIAL_OVERVIEW, Intent.SHOW_FINANCE, Intent.SHOW_INBOX,
    Intent.SHOW_BOOKINGS, Intent.SHOW_OPEN_ITEMS, Intent.SHOW_DEADLINES,
    Intent.SHOW_EXPENSE_CATEGORIES, Intent.SHOW_PROFIT_LOSS,
    Intent.SHOW_REVENUE_TREND, Intent.SHOW_FORECAST, Intent.PROCESS_INBOX,
})

_CHART_INTENT_MAP = {
    Intent.SHOW_INBOX: ('inbox_service', 'list_pending'),
    Intent.PROCESS_INBOX: ('inbox_service', 'process_first'),
    Intent.SHOW_FINANCIAL_OVERVIEW: ('euer_service', 'get_finance_summary'),
    Intent.SHOW_FINANCE: ('euer_service', 'get_finance_summary'),
    Intent.SHOW_BOOKINGS: ('booking_service', 'list'),
    Intent.SHOW_OPEN_ITEMS: ('open_item_service', 'list'),
    Intent.SHOW_DEADLINES: ('deadline_service', 'list'),
    Intent.SHOW_EXPENSE_CATEGORIES: ('booking_service', 'list'),
    Intent.SHOW_PROFIT_LOSS: ('euer_service', 'get_finance_summary'),
    Intent.SHOW_REVENUE_TREND: ('booking_service', 'list'),
    Intent.SHOW_FORECAST: ('euer_service', 'get_finance_summary'),
}

# Intent → Context-Type fuer Frontend
_TIER_INTENT_TO_CONTEXT = {
    Intent.SHOW_INBOX: 'inbox',
    Intent.PROCESS_INBOX: 'inbox',
    Intent.SHOW_FINANCIAL_OVERVIEW: 'finance',
    Intent.SHOW_FINANCE: 'finance',
    Intent.SHOW_BOOKINGS: 'bookings',
    Intent.SHOW_OPEN_ITEMS: 'open_items',
    Intent.SHOW_DEADLINES: 'deadlines',
    Intent.SHOW_EXPENSE_CATEGORIES: 'finance',
    Intent.SHOW_PROFIT_LOSS: 'finance',
    Intent.SHOW_REVENUE_TREND: 'finance',
    Intent.SHOW_FORECAST: 'finance',
    Intent.SHOW_CONTACTS: 'contacts',
    Intent.SHOW_CASE: 'case_detail',
    Intent.SHOW_INVOICE: 'invoice_detail',
    Intent.SETTINGS: 'settings',
    Intent.SHOW_EXPORT: 'export',
    Intent.CREATE_INVOICE: 'invoice_draft',
}


async def handle_shortcircuit_intent(
    intent: str,
    message: str,
    tenant_id: str,
    user_id: str,
    chat_id: str = None,
) -> Optional[dict]:
    """Verarbeitet einen Chart-Shortcircuit-Intent: Service aufrufen + ResponseBuilder.

    KRITISCH: Diese Funktion enthaelt die Chart-Builder-Logik.
    Finanzen ohne Charts = der Bug vom ersten Versuch (02a Abbruch).

    Returns:
        dict mit Response-Daten wenn verarbeitet, None wenn nicht.
    """
    if intent not in _CHART_SHORTCIRCUIT_INTENTS:
        return None

    try:
        from app.agents.service_registry import build_service_registry
        _chart_reg = build_service_registry()
        _si = _CHART_INTENT_MAP.get(intent)
        if not _si:
            return None

        _svc_obj = _chart_reg.get(_si[0])
        if not _svc_obj:
            return None

        _method = getattr(_svc_obj, _si[1], None)
        if not _method:
            return None

        # Service aufrufen MIT tenant_id (IMMER!)
        _chart_raw = await _method(tenant_id=tenant_id) or {}

        # Fix 5: ServiceResult → dict fuer Text-Sync, ResponseBuilder handled beides
        _chart_data = _chart_raw.data if hasattr(_chart_raw, 'data') else _chart_raw

        # ResponseBuilder aufrufen — HIER kommen die Charts!
        from app.agents.response_builder import ResponseBuilder
        _rb = ResponseBuilder()
        _rb_intent = intent
        # SHOW_FINANCIAL_OVERVIEW → SHOW_FINANCE fuer ResponseBuilder
        if intent == Intent.SHOW_FINANCIAL_OVERVIEW:
            _rb_intent = Intent.SHOW_FINANCE
        _sc_result = _rb.build(_rb_intent, _chart_data, '')
        _sc_blocks = _sc_result.get('content_blocks', [])
        _sc_actions = _sc_result.get('actions', [])

        # Text-Sync: Echte Zahlen statt LLM-Text
        _texts = {
            Intent.SHOW_INBOX: f'{_chart_data.get("count", len(_chart_data.get("items", [])))} Belege warten auf deine Freigabe.',
            Intent.PROCESS_INBOX: f'Beleg 1 von {_chart_data.get("count", 1)}: Hier sind die Details.' if _chart_data.get('status') == 'has_items' else 'Alles erledigt! Keine Belege warten auf dich.',
            Intent.SHOW_FINANCE: 'Hier ist deine Finanz\u00fcbersicht.',
            Intent.SHOW_FINANCIAL_OVERVIEW: 'Hier ist deine Finanz\u00fcbersicht.',
            Intent.SHOW_BOOKINGS: 'Hier sind deine letzten Buchungen.',
            Intent.SHOW_OPEN_ITEMS: 'Hier sind deine offenen Posten.',
            Intent.SHOW_DEADLINES: 'Hier sind deine anstehenden Fristen.',
            Intent.SHOW_EXPENSE_CATEGORIES: 'Hier ist die Aufschluesselung deiner Ausgaben nach Kategorie.',
            Intent.SHOW_PROFIT_LOSS: 'Hier ist deine Gewinn- und Verlustrechnung.',
            Intent.SHOW_REVENUE_TREND: 'Hier ist die Umsatzentwicklung.',
            Intent.SHOW_FORECAST: 'Hier ist die Hochrechnung fuer das Geschaeftsjahr.',
        }
        _reply = _texts.get(intent, 'Hier sind die Daten.')

        # Text-Sync fuer SHOW_FINANCE (Divergenz #5: REST-only → jetzt BEIDE)
        if intent in (Intent.SHOW_FINANCE, Intent.SHOW_FINANCIAL_OVERVIEW) and _chart_data:
            _fin_income = _chart_data.get('total_income', 0) or 0
            _fin_expense = _chart_data.get('total_expenses', _chart_data.get('total_expense', 0)) or 0
            _fin_profit = _chart_data.get('profit', _fin_income - _fin_expense)
            _fin_count = _chart_data.get('booking_count', 0)
            if _fin_count > 0:
                def _eur_fmt(v):
                    return f'{float(v):,.2f} \u20ac'.replace(',', 'X').replace('.', ',').replace('X', '.')
                _profit_f = float(_fin_profit)
                _ergebnis_label = f'{_eur_fmt(_fin_profit)} Gewinn' if _profit_f >= 0 else f'{_eur_fmt(abs(_profit_f))} Verlust'
                _reply = (
                    f'Hier ist deine Finanz\u00fcbersicht f\u00fcr 2026:\n'
                    f'Einnahmen: {_eur_fmt(_fin_income)}\n'
                    f'Ausgaben: {_eur_fmt(_fin_expense)}\n'
                    f'Ergebnis: {_ergebnis_label}\n'
                    f'({_fin_count} Buchungen)'
                )

        # Text-Sync fuer SHOW_INBOX
        if intent == Intent.SHOW_INBOX and _sc_blocks:
            _inbox_count = 0
            for _b in _sc_blocks:
                if _b.get('block_type') == 'card_list':
                    _inbox_count = len(_b.get('data', {}).get('items', []))
            if _inbox_count > 0:
                _total = _chart_data.get('count', _inbox_count)
                _reply = f'{_total} Belege warten auf deine Freigabe.'

        # Explicit quick_actions override ResponseBuilder
        _raw_actions = _chart_data.get('actions', [])
        if _raw_actions and any(a.get('quick_action') for a in _raw_actions):
            _sc_actions = _raw_actions

        # Sprint-03-03: generate_data_response bekommt chat_id statt chat_history+is_first_message
        # History wird direkt in generate_data_response aus Redis geladen (messages-Array)
        _effective_chat_id = chat_id or (f'web-{user_id}' if user_id else None)

        # Sprint-02-08: Llama generiert Text + Suggestions in EINEM Call
        # Sprint-03-03: chat_id statt chat_history (messages-Array, ChatGPT-Stil)
        # Fallback: Mistral-Text (_format_data_text) + statische Suggestions (_sc_actions)
        _llama = await generate_data_response(
            str(intent), _chart_data, message,
            chat_id=_effective_chat_id,
        )

        if _llama.get('text'):
            _reply = _llama['text']
        else:
            # Fallback Text: Mistral (wie Sprint-02-06)
            _mistral_text = await _format_data_text(str(intent), _chart_data, message)
            if _mistral_text:
                _reply = _mistral_text

        # Suggestions: Llama (spezifisch) > ResponseBuilder (statisch) > Default
        if _llama.get('suggestions'):
            _llama_actions = [
                {'label': s, 'chat_text': s, 'style': 'primary' if i == 0 else 'secondary'}
                for i, s in enumerate(_llama['suggestions'])
            ]
            _final_actions = _llama_actions
        else:
            _final_actions = _sc_actions if _sc_actions else []

        _final_suggestions = (
            [a['chat_text'] for a in _final_actions[:3]]
            if _final_actions else _DEFAULT_SUGGESTIONS
        )

        context_type = _TIER_INTENT_TO_CONTEXT.get(intent, 'none')

        return {
            'text': _reply,
            'case_ref': None,
            'context_type': context_type,
            'suggestions': _final_suggestions,
            'content_blocks': _sc_blocks,
            'actions': _final_actions,
            'routing': 'regex',
            '_service_data': _chart_data,   # Sprint-03-01: fuer save_to_history
            '_intent': str(intent),          # Sprint-03-01: fuer save_to_history
        }

    except Exception as exc:
        logger.warning('Chart shortcircuit failed: %s', exc)
        return None


# ============================================================
# SCHRITT 4: HISTORY-SAVE (RC-4 Fix + REGEL P3)
# Speichert IMMER — auch bei Shortcircuit. Auch im REST-Pfad.
# REGEL P3: Darf den Response NIEMALS blockieren.
# ============================================================

async def save_to_history(
    chat_id: str,
    user_message: str,
    assistant_text: str,
    service_data: dict = None,
    intent: str = None,
) -> None:
    """Speichert User-Nachricht + Antwort + optionaler Kontext in Redis Chat-History.

    IMMER aufrufen — bei Shortcircuit, Pending, Communicator.
    REGEL P3: Darf den Response NIEMALS blockieren.

    Sprint-03-01: service_data + intent → context_data in History.
    Ermoeglicht Frya Drill-Down-Fragen zu gerade angezeigten Daten.
    """
    try:
        from app.dependencies import get_chat_history_store
        hist = get_chat_history_store()
        if assistant_text:
            ctx = _build_context_summary(intent, service_data) if (service_data and intent) else None
            await hist.append(chat_id, user_message, assistant_text, context_data=ctx)
    except Exception as exc:
        logger.warning('Chat-History save failed for %s: %s', chat_id, exc)
        # NICHT re-raisen — Response darf nicht blockiert werden
