"""Drei-Ebenen-Routing: Regex (0ms) -> Mistral 24B (250ms) -> Llama 405B (5-30s)"""
import re, logging, os
from typing import Optional
import litellm

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 30


class TieredOrchestrator:
    FAST_PATTERNS = {
        # Specific patterns FIRST (before generic ones that might over-match)
        r"(?i)(zeig.*rechnung\s*RE-|rechnung\s*RE-\d+.*(?:aufrufen|anzeig|detail|öffn))": "SHOW_INVOICE",
        r"(?i)(rechnung.*(?:RE-\d+).*send|RE-\d+.*(?:send|freigeb|verschick))": "SEND_INVOICE",
        r"(?i)(rechnung.*erstell|schreib.*rechnung|rechnung an\s)": "CREATE_INVOICE",
        r"(?i)(rechnungs?.?(?:layout|vorlage|template|design)|template.*(?:wechsel|änder|wähl))": "CHOOSE_TEMPLATE",
        r"(?i)(clean|professional|minimal).?(?:template|vorlage)?\s*(?:wähl|nehm|bitte)": "SET_TEMPLATE",
        r"(?i)(logo.*(?:hochlad|upload|änder)|mein\s+logo)": "UPLOAD_LOGO",
        r"(?i)(wer schuldet|offene posten|offene rechnung|offene forderung)": "SHOW_OPEN_ITEMS",
        r"(?i)(inbox|belege|was liegt an|was steht an|abarbeiten)": "SHOW_INBOX",
        r"(?i)(eur|einnahmen|ausgaben|finanzen|wie steh|finanziell)": "SHOW_FINANCE",
        r"(?i)(frist|deadline|dringend|überfällig|was ist fällig)": "SHOW_DEADLINES",
        r"(?i)(zeig.*kontakt|meine\s*kontakte|alle\s*kontakte|alles über|kundenakte|kontaktliste)": "SHOW_CONTACTS",
        r"(?i)(buchungsjournal|buchungen zeig|journal)": "SHOW_BOOKINGS",
        r"(?i)(einstellung|dark.?mode|hell|dunkel|theme|anrede)": "SETTINGS",
        r"(?i)(export|datev|steuerberater)": "SHOW_EXPORT",
        r"(?i)(upload|wäschekorb|belege.*rein|stapel)": "UPLOAD",
        r"(?i)(kontakt.*anleg|neuer kontakt|kund.*anleg)": "CREATE_CONTACT",
        r"(?i)(mahnung|mahnen|zahlungserinnerung)": "CREATE_REMINDER",
    }

    DEEP_KEYWORDS = [
        "analysiere", "vergleiche", "warum", "was wäre wenn", "erkläre",
        "optimier", "steuer", "finanzamt", "einspruch", "widerspruch",
        "strategie", "prognose", "trend", "zusammenfass",
    ]

    VALID_INTENTS = {
        "SHOW_INBOX", "SHOW_FINANCE", "SHOW_DEADLINES", "SHOW_BOOKINGS",
        "SHOW_OPEN_ITEMS", "SHOW_CONTACT", "SHOW_CONTACTS", "SHOW_EXPORT", "CREATE_INVOICE",
        "CREATE_CONTACT", "CREATE_REMINDER", "APPROVE", "SETTINGS", "UPLOAD",
        "STATUS_OVERVIEW", "SMALL_TALK", "UNKNOWN",
        "SEND_INVOICE", "VOID_INVOICE", "EDIT_INVOICE", "SHOW_INVOICE",
        "CHOOSE_TEMPLATE", "SET_TEMPLATE", "UPLOAD_LOGO",
    }

    def __init__(self, action_router=None):
        self.action_router = action_router

    async def route(
        self,
        message: str,
        quick_action: dict = None,
        conversation_state: dict = None,
    ) -> dict:
        # Ebene 0: Quick Action (Button-Klick)
        if quick_action and self.action_router:
            logger.info("Routing via ActionRouter: %s", quick_action.get("type"))
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
        for pattern, intent in self.FAST_PATTERNS.items():
            if re.search(pattern, message):
                return intent
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
                return {"intent": "UNKNOWN", "routing": "fast_no_key", "message": message}

            resp = await litellm.acompletion(
                model=config['full_model'],
                messages=[{"role": "user", "content": classify_prompt}],
                max_tokens=20,
                timeout=15,
                api_key=config['api_key'],
                api_base=config.get('base_url'),
            )
            raw = (resp.choices[0].message.content or "").strip().upper().split()[0]
            intent = raw if raw in self.VALID_INTENTS else "UNKNOWN"
            if intent == "UNKNOWN":
                return {"intent": "COMPLEX", "routing": "deep", "message": message}
            return {"intent": intent, "routing": "fast", "message": message}
        except Exception as exc:
            logger.warning("Fast routing failed: %s, falling through to deep", exc)
            return {"intent": "COMPLEX", "routing": "deep", "message": message}
