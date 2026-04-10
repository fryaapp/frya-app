"""Drei-Ebenen-Routing: Regex (0ms) -> Mistral 24B (250ms) -> Llama 405B (5-30s)"""
import re, logging, os
from typing import Optional
import litellm

from app.core.intents import Intent, parse_intent

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 30


class TieredOrchestrator:
    # Shortcircuit-Hardening (Refactor 02c):
    # REGEL: Mindestens 2 Woerter oder eindeutiges Kompositum.
    # Einzelwoerter NUR mit ^...$ (ganzer Text muss matchen).
    # Bei Collision (mehrere Matches) → Orchestrator entscheidet.
    FAST_PATTERNS = {
        # ── Rechnungen (spezifisch ZUERST) ─────────────────────────
        r"(?i)(zeig.*rechnung\s*RE-|rechnung\s*RE-\d+.*(?:aufrufen|anzeig|detail|öffn))": Intent.SHOW_INVOICE,
        r"(?i)(rechnung.*(?:RE-\d+).*send|RE-\d+.*(?:send|freigeb|verschick))": Intent.SEND_INVOICE,
        r"(?i)(rechnung.*erstell|schreib.*rechnung|erstell.*rechnung|rechnung an\s|rechnung fuer\s|rechnung für\s)": Intent.CREATE_INVOICE,
        r"(?i)(storniere.*rechnung|rechnung.*storniere|rechnung.*(?:RE-\d+).*(?:storno|cancel))": Intent.CANCEL_INVOICE,
        # ── Templates / Logo ───────────────────────────────────────
        r"(?i)(rechnungs?.?(?:layout|vorlage|template|design)|template.*(?:wechsel|änder|wähl))": Intent.CHOOSE_TEMPLATE,
        r"(?i)(clean|professional|minimal).?(?:template|vorlage)?\s*(?:wähl|nehm|bitte)": Intent.SET_TEMPLATE,
        r"(?i)(logo.*(?:hochlad|upload|änder)|mein\s+logo)": Intent.UPLOAD_LOGO,
        # ── Offene Posten ──────────────────────────────────────────
        r"(?i)(wer schuldet|offene posten|offene rechnung|offene forderung)": Intent.SHOW_OPEN_ITEMS,
        # ── Inbox (spezifisch ZUERST) ──────────────────────────────
        r"(?i)(inbox\s*abarbeiten|belege\s*durchgehen|alle\s*belege\s*(?:prüfen|bearbeiten)|stapel\s*abarbeiten)": Intent.PROCESS_INBOX,
        r"(?i)(zeig.*inbox|meine inbox|offene belege|was liegt an|was steht an|zeig.*belege)": Intent.SHOW_INBOX,
        r"(?i)^(inbox|belege|abarbeiten)$": Intent.SHOW_INBOX,  # Einzelwoerter NUR als ganzer Text
        # ── Finanzen (Phrasen, KEIN Einzelwort) ────────────────────
        r"(?i)(ausgaben.*kategorie|kostenverteilung|wohin.*geld|kosten.*aufgeteilt|wo.*gebe.*meisten|am meisten aus|gr[oö]ßte.*posten|gr[oö]ßten.*posten)": Intent.SHOW_EXPENSE_CATEGORIES,
        r"(?i)(gewinn.*verlust|mein gewinn|guv|gewinn.*zeig|zeig.*gewinn)": Intent.SHOW_PROFIT_LOSS,
        r"(?i)(umsatz.*entwicklung|umsatz.*trend|umsatz.*verlauf)": Intent.SHOW_REVENUE_TREND,
        r"(?i)(hochrechnung|jahres.?hochrechnung|forecast)": Intent.SHOW_FORECAST,
        r"(?i)(eür|einnahmen.*übersicht|ausgaben.*übersicht|meine finanzen|wie steh.*finanziell|finanz.?übersicht|finanzen zeig|zeig.*finanzen|meine einnahmen|meine ausgaben)": Intent.SHOW_FINANCIAL_OVERVIEW,
        # ── Fristen (Phrasen) ──────────────────────────────────────
        r"(?i)(meine fristen|zeig.*fristen|was ist fällig|was ist überfällig|offene fristen|deadline.*zeig)": Intent.SHOW_DEADLINES,
        r"(?i)^(fristen|deadlines)$": Intent.SHOW_DEADLINES,
        # ── Kontakte ───────────────────────────────────────────────
        r"(?i)(zeig.*kontakt|meine\s*kontakte|alle\s*kontakte|kundenakte|kontaktliste)": Intent.SHOW_CONTACTS,
        r"(?i)^kontakte$": Intent.SHOW_CONTACTS,
        r"(?i)(kontakt.*anleg|neuer kontakt|kund.*anleg)": Intent.CREATE_CONTACT,
        # ── Buchungen ──────────────────────────────────────────────
        r"(?i)(buchungsjournal|buchungen zeig|zeig.*buchungen|meine buchungen)": Intent.SHOW_BOOKINGS,
        r"(?i)^journal$": Intent.SHOW_BOOKINGS,
        # ── Einstellungen ──────────────────────────────────────────
        r"(?i)(einstellung|dark.?mode|hell.*modus|dunkel.*modus|theme.*wechsel)": Intent.SETTINGS,
        r"(?i)^einstellungen$": Intent.SETTINGS,
        # ── Export ─────────────────────────────────────────────────
        r"(?i)(datev.*export|export.*datev|steuerberater|daten.*export|zeig.*export)": Intent.SHOW_EXPORT,
        r"(?i)^(export|datev)$": Intent.SHOW_EXPORT,
        # ── Upload ─────────────────────────────────────────────────
        r"(?i)(beleg.*hochlad|dokument.*hochlad|datei.*hochlad|belege.*rein)": Intent.UPLOAD,
        r"(?i)^upload$": Intent.UPLOAD,
        # ── Mahnung ────────────────────────────────────────────────
        r"(?i)(mahnung.*erstell|mahnung.*schreib|zahlungserinnerung)": Intent.CREATE_REMINDER,
        # ── Freigabe (Phrasen — "buchen" allein ist zu gierig) ────
        r"(?i)(bitte freigeb|jetzt freigeb|beleg freigeb|bitte buchen|jetzt buchen|buchung bestätig|CASE-\d{4}-\d{5}.*freigeb)": Intent.APPROVE,
        r"(?i)(\w+\s+freigeben)": Intent.APPROVE,  # "[Vendor] freigeben"
        # ── Kleinunternehmer ───────────────────────────────────────
        r"(?i)(kein\s+kleinunternehmer\s+mehr|nicht\s+mehr\s+kleinunternehmer|bin\s+wieder\s+kleinunternehmer|bin\s+kleinunternehmer|mit\s+(?:umsatz|mwst|mehrwert)steuer)": Intent.CHANGE_KU_STATUS,
    }

    DEEP_KEYWORDS = [
        "analysiere", "vergleiche", "warum", "was wäre wenn", "erkläre",
        "optimier", "steuer", "finanzamt", "einspruch", "widerspruch",
        "strategie", "prognose", "trend", "zusammenfass",
    ]

    # VALID_INTENTS: Jetzt automatisch aus dem Intent-Enum
    VALID_INTENTS = set(Intent)

    def __init__(self, action_router=None):
        self.action_router = action_router

    async def route(
        self,
        message: str,
        quick_action: dict = None,
        conversation_state: dict = None,
    ) -> dict:
        # Ebene 0: Quick Action (Button-Klick)
        if quick_action:
            qa_type = quick_action.get("type", "")
            # P-25: show_case bypasses ActionRouter — handled in Phase 1b via ResponseBuilder
            if qa_type == "show_case":
                logger.info("Routing show_case via quick_action (Phase 1b)")
                return {"intent": str(Intent.SHOW_CASE), "routing": "quick_action", "params": quick_action.get("params", {})}
            if self.action_router:
                logger.info("Routing via ActionRouter: %s", qa_type)
                result = await self.action_router.execute(quick_action)
                if result is not None:
                    return result

        # Ebene 1: Regex (<5ms) — Feature-Flag gesteuert
        from app.config import get_settings
        if get_settings().shortcircuit_enabled:
            intent = self._regex_match(message)
            if intent:
                logger.info("Routing via Regex: %s", intent)
                return {"intent": intent, "routing": "regex", "message": message}
        else:
            logger.info("Shortcircuit OFF — skipping regex, routing to LLM")

        # Ebene 2: LLM Intent-Klassifikation
        _settings = get_settings()
        if _settings.fast_tier_enabled and not self._needs_deep(message):
            logger.info("Routing via Fast (Mistral 24B)")
            return await self._route_fast(message)
        else:
            # Llama 3.3 70B klassifiziert — NICHT mehr blind "COMPLEX"
            logger.info("Routing via Llama 3.3 70B Classify")
            return await self._classify_with_llama(message)

    def _regex_match(self, message: str) -> Optional[str]:
        """Regex-Shortcircuit MIT Collision-Detection.
        Wenn MEHRERE verschiedene Intents matchen → None (Orchestrator entscheidet).
        Mehrere Patterns fuer den GLEICHEN Intent sind OK."""
        matched_intents: set[str] = set()
        for pattern, intent in self.FAST_PATTERNS.items():
            if re.search(pattern, message):
                matched_intents.add(intent)
        if len(matched_intents) == 1:
            return matched_intents.pop()
        if len(matched_intents) > 1:
            logger.info(
                'Shortcircuit COLLISION: "%s" matcht %s → Orchestrator entscheidet',
                message[:60], [str(m) for m in matched_intents],
            )
            return None
        return None

    def _needs_deep(self, message: str) -> bool:
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in self.DEEP_KEYWORDS):
            return True
        if len(message) > 200:
            return True
        return False

    async def _get_llm_config(self, agent_id: str) -> dict | None:
        """Load agent LLM config from DB (same mechanism as all other agents)."""
        try:
            from app.dependencies import get_llm_config_repository
            repo = get_llm_config_repository()
            config = await repo.get_config_or_fallback(agent_id)
            if not config or not config.get('model'):
                return None
            # Decrypt API key
            api_key = repo.decrypt_key_for_call(config)
            provider = (config.get('provider') or '').strip()
            model = (config.get('model') or '').strip()
            base_url = config.get('base_url')
            # Build full model name for litellm
            if provider == 'ionos':
                full_model = f'openai/{model}'
            elif provider and '/' not in model:
                full_model = f'{provider}/{model}'
            else:
                full_model = model
            return {
                'full_model': full_model,
                'api_key': api_key,
                'base_url': base_url,
            }
        except Exception as exc:
            logger.warning('Failed to load LLM config for %s: %s', agent_id, exc)
            return None

    async def _route_fast(self, message: str) -> dict:
        """Mistral 24B classifies intent via DB-configured orchestrator_router agent."""
        classify_prompt = (
            "Klassifiziere die User-Nachricht in EINEN Intent.\n"
            "Mögliche Intents:\n"
            "- SHOW_INBOX: Inbox, Belege, was liegt an, was gibt es Neues, alle durchgehen, dringende Belege\n"
            "- SHOW_FINANCE: Finanzen, Finanzuebersicht, Einnahmen, Ausgaben, EUeR, wie stehe ich finanziell\n"
            "- SHOW_EXPENSE_CATEGORIES: wo gebe ich am meisten aus, groesste Posten, Ausgaben nach Kategorie, teuerste Ausgaben\n"
            "- SHOW_OPEN_ITEMS: Offene Posten, wer schuldet, Forderungen, Mahnung, Schuldner, offene Rechnungen pruefen, wer ist ueberfaellig\n"
            "- SHOW_DEADLINES: Fristen, dringend, faellig, Termine\n"
            "- SHOW_BOOKINGS: Buchungen, Kontobewegungen, Buchungen anzeigen\n"
            "- SHOW_CONTACT, SHOW_CONTACTS: Kontakt(e) suchen/anzeigen\n"
            "- SHOW_EXPORT: Export, DATEV, CSV, EUeR als PDF, DATEV-Export\n"
            "- CREATE_INVOICE: Rechnung erstellen/schreiben\n"
            "- CREATE_CONTACT: Kontakt anlegen\n"
            "- CREATE_REMINDER: Mahnung schreiben, Erinnerung setzen, Mahnung an [Name]\n"
            "- PROCESS_INBOX: Belege abarbeiten, Inbox durchgehen, Beleg freigeben, alles durchgehen\n"
            "- APPROVE: Freigeben, genehmigen\n"
            "- SETTINGS: Einstellungen, Profil, Theme\n"
            "- UPLOAD: Beleg hochladen\n"
            "- SMALL_TALK: Begruessung, Danke, Smalltalk\n"
            "- UNKNOWN: Unklar\n"
            "BEISPIELE fuer Suggestion-Buttons:\n"
            '"Wo gebe ich am meisten aus?" → SHOW_EXPENSE_CATEGORIES\n'
            '"EUeR als PDF" → SHOW_EXPORT\n'
            '"Offene Rechnungen pruefen" → SHOW_OPEN_ITEMS\n'
            '"Weber eine Mahnung schreiben" → CREATE_REMINDER\n'
            '"Alle offenen Posten anzeigen" → SHOW_OPEN_ITEMS\n'
            '"Buchungen anzeigen" → SHOW_BOOKINGS\n'
            '"Alle durchgehen" → PROCESS_INBOX\n'
            f'Nachricht: "{message}"\n'
            "Antworte NUR mit dem Intent-Namen."
        )
        try:
            config = await self._get_llm_config('orchestrator_router')
            if not config or not config.get('api_key'):
                return {"intent": str(Intent.UNKNOWN), "routing": "fast_no_key", "message": message}

            resp = await litellm.acompletion(
                model=config['full_model'],
                messages=[{"role": "user", "content": classify_prompt}],
                max_tokens=20,
                timeout=15,
                api_key=config['api_key'],
                api_base=config.get('base_url'),
            )
            raw = (resp.choices[0].message.content or "").strip().upper().split()[0]
            intent = parse_intent(raw)
            if intent == Intent.UNKNOWN:
                return {"intent": "COMPLEX", "routing": "deep", "message": message}
            return {"intent": str(intent), "routing": "fast", "message": message}
        except Exception as exc:
            logger.warning("Fast routing failed: %s, falling through to deep", exc)
            return {"intent": "COMPLEX", "routing": "deep", "message": message}

    async def _classify_with_llama(self, message: str) -> dict:
        """Llama 3.3 70B klassifiziert den Intent.

        Gibt einen ECHTEN Intent zurueck (nicht COMPLEX).
        Nutzt die DB-Config 'orchestrator' (Llama 3.3 70B auf IONOS).
        Gleicher Output-Format wie _route_fast() damit die Service Registry matcht.
        """
        classify_prompt = (
            "Du bist der Intent-Classifier fuer FRYA, ein deutsches Buchhaltungssystem.\n"
            "Analysiere die Nachricht und gib GENAU EINEN Intent zurueck.\n\n"
            "VERFUEGBARE INTENTS:\n"
            "- SHOW_INBOX: Inbox, Belege, was liegt an, was gibt es Neues, dringende Belege\n"
            "- SHOW_FINANCE: Finanzen, Finanzuebersicht, Einnahmen, Ausgaben, EUeR, wie stehe ich finanziell\n"
            "- SHOW_FINANCIAL_OVERVIEW: Gleich wie SHOW_FINANCE\n"
            "- SHOW_EXPENSE_CATEGORIES: wo gebe ich am meisten aus, groesste Posten, Ausgaben nach Kategorie, teuerste Ausgaben, Kostenaufteilung\n"
            "- SHOW_OPEN_ITEMS: Offene Posten, wer schuldet mir, Forderungen, Schuldner, offene Rechnungen pruefen, Gesamtschulden, ueberfaellig\n"
            "- SHOW_DEADLINES: Fristen, dringend, faellig, Termine\n"
            "- SHOW_BOOKINGS: Buchungen, Buchungsjournal, Kontobewegungen, Buchungen anzeigen\n"
            "- SHOW_CONTACTS: Kontakte, Kunden, Lieferanten anzeigen\n"
            "- SHOW_CONTACT: Einen bestimmten Kontakt suchen/anzeigen\n"
            "- SHOW_CASE: Einen bestimmten Beleg/Vorgang/Fall anzeigen\n"
            "- SHOW_EXPORT: Export, DATEV, CSV, EUeR als PDF, DATEV-Export, Steuerexport\n"
            "- CREATE_INVOICE: Rechnung erstellen/schreiben\n"
            "- CREATE_CONTACT: Kontakt anlegen\n"
            "- CREATE_REMINDER: Mahnung schreiben, Erinnerung/Mahnung erstellen, Mahnung an [Name]\n"
            "- APPROVE: Freigeben, genehmigen, buchen\n"
            "- PROCESS_INBOX: Inbox abarbeiten, Belege durchgehen, alle durchgehen, alles abarbeiten\n"
            "- SETTINGS: Einstellungen, Profil, Theme\n"
            "- UPLOAD: Beleg hochladen\n"
            "- GENERAL_CONVERSATION: Begruessung, Danke, Smalltalk, oder wenn unklar\n\n"
            "WICHTIGE REGELN:\n"
            "1. 'Geld schulden', 'Forderungen', 'Mahnung', 'wer schuldet', 'offene Rechnungen pruefen' → SHOW_OPEN_ITEMS (NICHT SHOW_FINANCE!)\n"
            "2. 'Wo gebe ich am meisten aus', 'groesste Posten', 'Ausgaben nach Kategorie' → SHOW_EXPENSE_CATEGORIES (NICHT SHOW_FINANCE!)\n"
            "3. 'Rechnung erstellen/schreiben', Betraege im Kontext einer Rechnung → CREATE_INVOICE\n"
            "4. 'EUeR als PDF', 'DATEV-Export', 'Export' → SHOW_EXPORT\n"
            "5. 'Euro'/'Betrag'/'Preis' allein sind KEIN Grund fuer SHOW_FINANCE — pruefe den Kontext\n"
            "6. SHOW_FINANCE/SHOW_FINANCIAL_OVERVIEW nur wenn User EXPLIZIT nach Finanzuebersicht/EUeR fragt\n"
            "7. Wenn unklar → GENERAL_CONVERSATION\n\n"
            "BEISPIELE:\n"
            '"Wer schuldet mir Geld?" → SHOW_OPEN_ITEMS\n'
            '"Erstelle eine Rechnung ueber 500 Euro" → CREATE_INVOICE\n'
            '"Wie stehe ich finanziell?" → SHOW_FINANCIAL_OVERVIEW\n'
            '"Was liegt in der Inbox?" → SHOW_INBOX\n'
            '"Was habe ich bei Stabilo gekauft?" → SHOW_CASE\n'
            '"Zeig mir meine Buchungen" → SHOW_BOOKINGS\n'
            '"Wo gebe ich am meisten aus?" → SHOW_EXPENSE_CATEGORIES\n'
            '"EUeR als PDF" → SHOW_EXPORT\n'
            '"Offene Rechnungen pruefen" → SHOW_OPEN_ITEMS\n'
            '"Weber eine Mahnung schreiben" → CREATE_REMINDER\n'
            '"Alle durchgehen" → PROCESS_INBOX\n'
            '"Buchungen anzeigen" → SHOW_BOOKINGS\n'
            '"Hallo Frya" → GENERAL_CONVERSATION\n\n'
            f'Nachricht: "{message}"\n\n'
            "Antworte mit GENAU EINEM Intent-String, nichts anderes."
        )
        try:
            config = await self._get_llm_config('orchestrator')
            if not config or not config.get('api_key'):
                logger.warning("Llama classify: no config for 'orchestrator', falling back to GENERAL_CONVERSATION")
                return {"intent": str(Intent.GENERAL_CONVERSATION), "routing": "deep_no_key", "message": message}

            resp = await litellm.acompletion(
                model=config['full_model'],
                messages=[{"role": "user", "content": classify_prompt}],
                max_tokens=20,
                timeout=_LLM_TIMEOUT,
                temperature=0.1,
                api_key=config['api_key'],
                api_base=config.get('base_url'),
            )
            raw = (resp.choices[0].message.content or "").strip().upper().split()[0]
            intent = parse_intent(raw)
            logger.info("Llama classify: '%s' → %s", message[:50], intent)
            if intent == Intent.UNKNOWN:
                return {"intent": str(Intent.GENERAL_CONVERSATION), "routing": "deep", "message": message}
            return {"intent": str(intent), "routing": "deep", "message": message}
        except Exception as exc:
            logger.warning("Llama classify failed: %s → GENERAL_CONVERSATION", exc)
            return {"intent": str(Intent.GENERAL_CONVERSATION), "routing": "deep", "message": message}
