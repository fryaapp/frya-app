"""Assembliert content_blocks und actions fuer WebSocket-Response."""
from __future__ import annotations
from typing import Any

from app.utils.translations import t_doc_type, t_confidence

_CONF_TO_FLOAT = {
    "CERTAIN": 0.95,
    "HIGH": 0.85,
    "MEDIUM": 0.65,
    "LOW": 0.35,
    "UNKNOWN": 0.0,
}


class ResponseBuilder:
    def build(
        self,
        intent: str,
        agent_results: dict,
        communicator_text: str,
        state: dict | None = None,
    ) -> dict:
        blocks = self._build_content_blocks(intent, agent_results)
        actions = self._build_actions(intent, agent_results, state)
        return {
            "type": "message_complete",
            "text": communicator_text,
            "content_blocks": blocks,
            "actions": actions,
            "suggestions": [a["chat_text"] for a in actions[:3]],
        }

    def _build_content_blocks(self, intent: str, results: dict) -> list[dict]:
        if intent == "SHOW_INBOX" and results.get("items"):
            all_items = results["items"]
            preview = all_items[:3]  # Max 3 Cards anzeigen
            remaining = len(all_items) - len(preview)
            title = f"{len(all_items)} Belege warten"
            blocks: list[dict] = [
                {
                    "block_type": "card_list",
                    "data": {
                        "title": title,
                        "items": [self._card(i) for i in preview],
                    },
                }
            ]
            if remaining > 0:
                blocks.append({
                    "block_type": "alert",
                    "data": {
                        "severity": "info",
                        "text": f"+ {remaining} weitere Belege. Sag 'alle zeigen' um die komplette Liste zu sehen.",
                    },
                })
            return blocks
        if intent == "APPROVE" and results.get("next_item"):
            return [{"block_type": "card", "data": self._card(results["next_item"])}]
        if intent == "SHOW_FINANCE" and (results.get("summary") or results.get("total_income") is not None):
            s = results.get("summary") or results
            blocks: list[dict] = [
                {
                    "block_type": "key_value",
                    "data": {
                        "items": [
                            {
                                "label": "Einnahmen",
                                "value": self._eur(s.get("total_income", s.get("income", 0))),
                            },
                            {
                                "label": "Ausgaben",
                                "value": self._eur(s.get("total_expenses", s.get("expenses", 0))),
                            },
                            {
                                "label": "Ergebnis",
                                "value": self._eur(s.get("profit", (s.get("total_income", 0) or 0) - (s.get("total_expenses", 0) or 0))),
                            },
                        ]
                    },
                }
            ]
            return blocks
        if intent == "SHOW_DEADLINES" and results.get("deadlines"):
            return [
                {
                    "block_type": "card_list",
                    "data": {
                        "items": [
                            self._deadline_card(d) for d in results["deadlines"]
                        ],
                    },
                }
            ]
        if intent == "SHOW_CONTACT" and results.get("dossier"):
            d = results["dossier"]
            return [
                {
                    "block_type": "key_value",
                    "data": {
                        "title": d["contact"]["name"],
                        "items": [
                            {
                                "label": "Kategorie",
                                "value": d["contact"].get("category", "\u2014"),
                            },
                            {
                                "label": "E-Mail",
                                "value": d["contact"].get("email", "\u2014"),
                            },
                            {
                                "label": "Gesamtumsatz",
                                "value": self._eur(d["stats"]["total_revenue"]),
                            },
                            {
                                "label": "Offener Betrag",
                                "value": self._eur(d["stats"]["open_amount"]),
                            },
                        ],
                    },
                }
            ]
        if intent == "CREATE_INVOICE" and results.get("form"):
            return [{"block_type": "form", "data": results["form"]}]
        return []

    def _build_actions(
        self, intent: str, results: dict, state: dict | None = None
    ) -> list[dict]:
        if intent == "APPROVE" and results.get("next_item"):
            ni = results["next_item"]
            cid = ni.get("case_id", "")
            return [
                {
                    "label": "Freigeben",
                    "chat_text": f"{ni.get('vendor', '')} freigeben",
                    "style": "primary",
                    "quick_action": {
                        "type": "approve",
                        "params": {"case_id": cid},
                    },
                },
                {
                    "label": "\u00dcberspringen",
                    "chat_text": "N\u00e4chster",
                    "style": "text",
                    "quick_action": {
                        "type": "defer",
                        "params": {"case_id": cid},
                    },
                },
            ]
        if intent == "SHOW_INBOX" and results.get("items"):
            first = results["items"][0]
            return [
                {
                    "label": "Abarbeiten",
                    "chat_text": "Inbox abarbeiten",
                    "style": "primary",
                    "quick_action": {
                        "type": "approve",
                        "params": {"case_id": first.get("case_id", "")},
                    },
                },
                {
                    "label": "Nur dringende",
                    "chat_text": "Nur dringende Belege",
                    "style": "secondary",
                },
            ]
        if intent == "SHOW_FINANCE":
            return [
                {
                    "label": "E\u00dcR als PDF",
                    "chat_text": "E\u00dcR als PDF",
                    "style": "secondary",
                },
                {
                    "label": "DATEV Export",
                    "chat_text": "DATEV Export",
                    "style": "secondary",
                },
            ]
        return [
            {
                "label": "Inbox",
                "chat_text": "Was liegt in der Inbox?",
                "style": "secondary",
            },
            {
                "label": "Finanzen",
                "chat_text": "Wie stehen die Finanzen?",
                "style": "secondary",
            },
        ]

    def _card(self, item: dict) -> dict:
        # A.2: Vendor "?" -> "Unbekannter Absender"
        vendor = item.get("vendor", item.get("name", ""))
        if not vendor or vendor.strip() in ("?", "", "None", "null"):
            vendor = "Unbekannter Absender"

        # A.5: Confidence float/string normalization
        conf = item.get("confidence", 0)
        if isinstance(conf, str):
            conf = _CONF_TO_FLOAT.get(conf.upper(), 0.5)

        # A.5: Confidence label with German translation
        if not item.get("confidence_label"):
            if conf >= 0.85:
                label = "Sicher"
            elif conf >= 0.65:
                label = "Hoch"
            elif conf >= 0.40:
                label = "Mittel"
            else:
                label = "Niedrig"
        else:
            label = t_confidence(item.get("confidence_label", "?"))

        return {
            "title": vendor,
            "subtitle": t_doc_type(item.get("document_type", "")),
            "amount": self._eur(item.get("amount")) if item.get("amount") else None,
            "badge": {
                "label": label,
                "color": self._conf_color(conf),
            },
            "ai_label": "KI-Vorschlag \u00b7 bitte pr\u00fcfen",
        }

    def _deadline_card(self, dl: dict) -> dict:
        days = dl.get("days_remaining", 0)
        overdue = " \u00fcberf\u00e4llig" if days < 0 else ""
        return {
            "title": dl.get("title", "?"),
            "subtitle": dl.get("subtitle", ""),
            "badge": {
                "label": f"{abs(days)}d{overdue}",
                "color": (
                    "error"
                    if days < 0
                    else "warning" if days < 7 else "info"
                ),
            },
        }

    @staticmethod
    def _eur(a: Any) -> str:
        if a is None:
            return "\u2014"
        return f"{float(a):,.2f} \u20ac".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _conf_color(c: float | None) -> str:
        if c is None:
            return "warning"
        if c >= 0.85:
            return "success"
        if c >= 0.65:
            return "info"
        if c >= 0.40:
            return "warning"
        return "error"
