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
        r"(?i)(ausgaben.*kategorie|kostenverteilung|wohin.*geld|kosten.*aufgeteilt)": Intent.SHOW_EXPENSE_CATEGORIES,
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

        # Ebene 1: Regex (<5ms)
        intent = self._regex_match(message)
        if intent:
            logger.info("Routing via Regex: %s", intent)
            return {"intent": intent, "routing": "regex", "message": message}

        # Deep oder Fast?
        if self._needs_deep(message):
            logger.info("Routing via Deep (existing orchestrator)")
            return {"intent": "COMPLEX", "routing": "deep", "message": message}
        else:
            logger.info("Routing via Fast (Mistral 24B)")
            return await self._route_fast(message)

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
            "Mögliche: SHOW_INBOX, SHOW_FINANCE, SHOW_DEADLINES, SHOW_BOOKINGS, "
            "SHOW_OPEN_ITEMS, SHOW_CONTACT, SHOW_CONTACTS, SHOW_EXPORT, CREATE_INVOICE, "
            "CREATE_CONTACT, CREATE_REMINDER, APPROVE, SETTINGS, UPLOAD, "
            "STATUS_OVERVIEW, SMALL_TALK, UNKNOWN\n"
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
