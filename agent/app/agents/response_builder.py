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
    CONTEXT_SUGGESTIONS = {
        "SHOW_INBOX": [
            {"label": "Abarbeiten", "chat_text": "Inbox abarbeiten", "style": "primary"},
            {"label": "Nur dringende", "chat_text": "Nur dringende Belege", "style": "secondary"},
        ],
        "APPROVE": [
            {"label": "Finanzen", "chat_text": "Wie stehen die Finanzen?", "style": "secondary"},
            {"label": "Inbox", "chat_text": "Was liegt in der Inbox?", "style": "text"},
        ],
        "SHOW_FINANCE": [
            {"label": "EUeR als PDF", "chat_text": "EUeR als PDF", "style": "primary"},
            {"label": "DATEV Export", "chat_text": "DATEV Export", "style": "secondary"},
            {"label": "Ausgaben Detail", "chat_text": "Was waren meine groessten Ausgaben?", "style": "text"},
        ],
        "SHOW_BOOKINGS": [
            {"label": "Filtern", "chat_text": "Buchungen im Maerz", "style": "secondary"},
            {"label": "Finanzen", "chat_text": "Wie stehen die Finanzen?", "style": "text"},
        ],
        "SHOW_CONTACT": [
            {"label": "Fall bearbeiten", "chat_text": "Fall bearbeiten", "style": "primary"},
            {"label": "Rechnung schreiben", "chat_text": "Rechnung schreiben", "style": "secondary"},
            {"label": "Naechster Fall", "chat_text": "Naechster Fall", "style": "text"},
        ],
        "SHOW_OPEN_ITEMS": [
            {"label": "Mahnen", "chat_text": "Ueberfaellige mahnen", "style": "primary"},
            {"label": "Details", "chat_text": "Zeig mir den aeltesten offenen Posten", "style": "secondary"},
        ],
        "SHOW_DEADLINES": [
            {"label": "Skonto nutzen", "chat_text": "Welche Skonto-Fristen laufen?", "style": "primary"},
            {"label": "Inbox", "chat_text": "Was liegt in der Inbox?", "style": "text"},
        ],
        "CREATE_INVOICE": [
            {"label": "Vorschau", "chat_text": "Zeig mir die Rechnung", "style": "primary"},
        ],
        "SHOW_EXPORT": [
            {"label": "EUeR dazu", "chat_text": "EUeR als PDF", "style": "secondary"},
        ],
        "SETTINGS": [
            {"label": "Profil bearbeiten", "chat_text": "Firmendaten aendern", "style": "primary"},
            {"label": "Dunkelmodus", "chat_text": "Dunkelmodus an", "style": "secondary"},
            {"label": "Heller Modus", "chat_text": "Heller Modus", "style": "secondary"},
        ],
        "UPLOAD": [
            {"label": "Inbox pruefen", "chat_text": "Was liegt in der Inbox?", "style": "primary"},
        ],
        "CHOOSE_TEMPLATE": [
            {"label": "Clean", "chat_text": "Clean-Template waehlen", "style": "primary",
             "quick_action": {"type": "set_template", "params": {"template": "clean"}}},
            {"label": "Professional", "chat_text": "Professional-Template waehlen", "style": "secondary",
             "quick_action": {"type": "set_template", "params": {"template": "professional"}}},
            {"label": "Minimal", "chat_text": "Minimal-Template waehlen", "style": "text",
             "quick_action": {"type": "set_template", "params": {"template": "minimal"}}},
        ],
        "SET_TEMPLATE": [
            {"label": "Rechnung erstellen", "chat_text": "Rechnung erstellen", "style": "primary"},
            {"label": "Vorschau ansehen", "chat_text": "Rechnungs-Vorschau zeigen", "style": "secondary"},
        ],
        "UPLOAD_LOGO": [
            {"label": "Logo hochladen", "chat_text": "Logo hochladen", "style": "primary"},
        ],
        "SHOW_FINANCIAL_OVERVIEW": [
            {"label": "Ausgaben Detail", "chat_text": "Ausgaben nach Kategorie", "style": "primary"},
            {"label": "Gewinn/Verlust", "chat_text": "Wie ist mein Gewinn?", "style": "secondary"},
            {"label": "Prognose", "chat_text": "Hochrechnung", "style": "text"},
        ],
        "SHOW_EXPENSE_CATEGORIES": [
            {"label": "Finanzen", "chat_text": "Wie stehen die Finanzen?", "style": "secondary"},
            {"label": "Umsatztrend", "chat_text": "Umsatzentwicklung", "style": "text"},
        ],
        "SHOW_PROFIT_LOSS": [
            {"label": "Prognose", "chat_text": "Hochrechnung", "style": "primary"},
            {"label": "Umsatztrend", "chat_text": "Umsatzentwicklung", "style": "secondary"},
        ],
        "SHOW_REVENUE_TREND": [
            {"label": "Gewinn/Verlust", "chat_text": "Wie ist mein Gewinn?", "style": "secondary"},
            {"label": "Prognose", "chat_text": "Hochrechnung", "style": "text"},
        ],
        "SHOW_FORECAST": [
            {"label": "Finanzen", "chat_text": "Wie stehen die Finanzen?", "style": "secondary"},
            {"label": "Ausgaben", "chat_text": "Ausgaben nach Kategorie", "style": "text"},
        ],
    }

    FALLBACK_SUGGESTIONS = [
        {"label": "Inbox", "chat_text": "Was liegt in der Inbox?", "style": "secondary"},
        {"label": "Finanzen", "chat_text": "Wie stehen die Finanzen?", "style": "secondary"},
    ]

    def build(
        self,
        intent: str,
        agent_results: dict,
        communicator_text: str,
        state: dict | None = None,
        llm_suggestions: list[dict] | None = None,
    ) -> dict:
        blocks = self._build_content_blocks(intent, agent_results)

        # Aufgabe 5: Filter empty blocks
        blocks = [b for b in blocks if self._block_has_data(b)]

        # Aufgabe 3: LLM suggestions > static matrix (except APPROVE which has quick_actions)
        if llm_suggestions and intent not in ('APPROVE',):
            actions = llm_suggestions
        else:
            actions = self._build_actions(intent, agent_results, state)
        return {
            "type": "message_complete",
            "text": communicator_text,
            "content_blocks": blocks,
            "actions": actions,
            "suggestions": [a["chat_text"] for a in actions[:3]],
        }

    @staticmethod
    def _block_has_data(block: dict) -> bool:
        """Aufgabe 5: Return False for empty/useless blocks."""
        if not block or not block.get("data"):
            return False
        data = block["data"]
        bt = block.get("block_type", "")
        if bt == "key_value":
            items = data.get("items", [])
            filled = [i for i in items if i.get("value") and str(i["value"]).strip() not in ("", "\u2014", "None", "?", "0,00 \u20ac")]
            return len(filled) > 0
        if bt == "card_list":
            return bool(data.get("items"))
        if bt == "table":
            return bool(data.get("rows"))
        return True

    # ------------------------------------------------------------------ #
    #  Content-Block dispatch (covers ALL intents)                        #
    # ------------------------------------------------------------------ #

    def _build_content_blocks(self, intent: str, results: dict) -> list[dict]:
        """Dispatch to intent-specific builder via naming convention."""
        builder = getattr(self, f"_blocks_{intent.lower()}", None)
        if builder:
            try:
                return builder(results)
            except Exception:
                pass
        # Fallback: Communicator text is always shown; no extra blocks.
        return []

    # --- per-intent block builders ------------------------------------ #

    def _blocks_show_inbox(self, results: dict) -> list[dict]:
        items = results.get("items", [])
        if not items:
            return [{"block_type": "alert", "data": {"severity": "success", "text": "Keine Belege in der Inbox. Alles erledigt!"}}]

        # Aufgabe 4: Send ALL items — frontend handles expand/collapse
        title = f"{len(items)} Belege warten"
        blocks: list[dict] = [
            {
                "block_type": "card_list",
                "data": {
                    "title": title,
                    "items": [self._card(i) for i in items],
                    "initial_count": 5,  # Frontend shows 5 initially, rest expandable
                },
            }
        ]
        return blocks

    def _blocks_approve(self, results: dict) -> list[dict]:
        if results.get("next_item"):
            blocks = [{"block_type": "card", "data": self._card(results["next_item"])}]
            # Only show "Freigabe erledigt" if the approval was actually executed
            if results.get("approved"):
                blocks.insert(0, {"block_type": "alert", "data": {"severity": "success", "text": "Freigabe erledigt."}})
            return blocks
        if results.get("approved"):
            return [{"block_type": "alert", "data": {"severity": "success", "text": "Freigabe erledigt. Alle Belege bearbeitet!"}}]
        return [{"block_type": "alert", "data": {"severity": "info", "text": "Kein Beleg zum Freigeben gefunden."}}]

    def _blocks_show_finance(self, results: dict) -> list[dict]:
        s = results.get("summary", results)
        income = s.get("total_income", s.get("income", 0)) or 0
        expenses = s.get("total_expenses", s.get("expenses", 0)) or 0
        profit = s.get("profit", None)
        if profit is None:
            profit = (float(income) if income else 0) - (float(expenses) if expenses else 0)
        blocks: list[dict] = []
        # P-11 A2: bar_chart for income vs expenses
        blocks.append({"block_type": "chart", "data": {
            "title": "Einnahmen vs. Ausgaben",
            "chart_type": "bar",
            "series": [
                {"label": "Einnahmen", "value": round(float(income), 2), "color": "#66E07A"},
                {"label": "Ausgaben", "value": round(float(expenses), 2), "color": "#FF8A80"},
                {"label": "Gewinn", "value": round(float(profit), 2), "color": "#F08A3A"},
            ],
        }})
        blocks.append({"block_type": "key_value", "data": {"items": [
            {"label": "Einnahmen", "value": self._eur(income)},
            {"label": "Ausgaben", "value": self._eur(expenses)},
            {"label": "Ergebnis", "value": self._eur(profit)},
        ]}})
        return blocks

    def _blocks_show_eur(self, results: dict) -> list[dict]:
        return self._blocks_show_finance(results)

    def _blocks_show_bookings(self, results: dict) -> list[dict]:
        bookings = results if isinstance(results, list) else results.get("bookings", results.get("items", []))
        if not isinstance(bookings, list):
            bookings = []
        rows = []
        for b in bookings[:30]:
            if not isinstance(b, dict):
                continue
            rows.append({
                "Nr": str(b.get("booking_number", "")),
                "Datum": str(b.get("booking_date", "")),
                "Beschreibung": str(b.get("description", ""))[:50],
                "Betrag": self._eur(b.get("amount", b.get("gross_amount", 0))),
                "Konto": str(b.get("debit_account", b.get("skr03_soll", ""))),
            })
        if not rows:
            return [{"block_type": "alert", "data": {"severity": "info", "text": "Noch keine Buchungen vorhanden."}}]
        return [{"block_type": "table", "data": {"columns": ["Nr", "Datum", "Beschreibung", "Betrag", "Konto"], "rows": rows}}]

    def _blocks_show_open_items(self, results: dict) -> list[dict]:
        items = results if isinstance(results, list) else results.get("items", results.get("open_items", []))
        if not isinstance(items, list):
            items = []
        if not items:
            return [{"block_type": "alert", "data": {"severity": "success", "text": "Keine offenen Posten."}}]
        cards = []
        for op in items[:10]:
            if not isinstance(op, dict):
                continue
            days = op.get("days_overdue", 0)
            overdue = days > 0 if isinstance(days, (int, float)) else False
            cards.append({
                "title": str(op.get("contact_name", op.get("vendor", op.get("description", "?")))),
                "subtitle": str(op.get("due_date", "")),
                "amount": self._eur(op.get("remaining_amount", op.get("amount", op.get("original_amount", 0)))),
                "badge": {"label": f"{days}d ueberfaellig" if overdue else "Offen", "color": "error" if overdue else "warning"},
            })
        blocks: list[dict] = []
        # P-11 A2: KPI + summary chart for OP
        total_open = sum(float(op.get("remaining_amount", op.get("amount", op.get("original_amount", 0))) or 0) for op in items if isinstance(op, dict))
        overdue_count = sum(1 for op in items if isinstance(op, dict) and (op.get("days_overdue", 0) or 0) > 0)
        blocks.append({"block_type": "chart", "data": {
            "title": "Offene Posten",
            "chart_type": "donut",
            "center_value": self._eur(total_open),
            "center_label": "Gesamt offen",
            "series": [
                {"label": "Ueberfaellig", "value": overdue_count, "color": "#FF8A80"},
                {"label": "Offen", "value": len(items) - overdue_count, "color": "#FFD54F"},
            ],
        }})
        blocks.append({"block_type": "card_list", "data": {"title": f"{len(items)} offene Posten", "items": cards}})
        return blocks

    def _blocks_show_deadlines(self, results: dict) -> list[dict]:
        items = results if isinstance(results, list) else results.get("deadlines", results.get("items", []))
        if not isinstance(items, list):
            items = []
        if not items:
            return [{"block_type": "alert", "data": {"severity": "success", "text": "Keine anstehenden Fristen."}}]
        cards = []
        for d in items:
            if not isinstance(d, dict):
                continue
            days = d.get("days_remaining", d.get("days", 99))
            color = "error" if days < 0 else "warning" if days <= 7 else "info" if days <= 30 else "success"
            label_text = "Ueberfaellig" if days < 0 else f"{days} Tage"
            cards.append({
                "title": str(d.get("vendor", d.get("name", d.get("description", d.get("title", "?"))))),
                "subtitle": str(d.get("due_date", "")),
                "badge": {"label": label_text, "color": color},
            })
        return [{"block_type": "card_list", "data": {"items": cards}}]

    def _blocks_show_contacts(self, results: dict) -> list[dict]:
        """P-08 A2: Kontaktliste als card_list."""
        contacts = results if isinstance(results, list) else results.get("contacts", results.get("items", []))
        if not isinstance(contacts, list):
            contacts = []
        if not contacts:
            return [{"block_type": "alert", "data": {"severity": "info", "text": "Keine Kontakte vorhanden."}}]
        cards = []
        for c in contacts[:20]:
            if not isinstance(c, dict):
                continue
            name = c.get("name") or c.get("display_name") or "?"
            ctype = c.get("contact_type", "")
            type_label = {"CUSTOMER": "Kunde", "VENDOR": "Lieferant", "BOTH": "Kunde/Lieferant"}.get(ctype, ctype)
            subtitle_parts = []
            if type_label:
                subtitle_parts.append(type_label)
            email = c.get("email")
            if email:
                subtitle_parts.append(email)
            cards.append({
                "title": name,
                "subtitle": " · ".join(subtitle_parts) if subtitle_parts else "\u2014",
            })
        return [{"block_type": "card_list", "data": {"title": f"{len(contacts)} Kontakte", "items": cards}}]

    def _blocks_show_contact(self, results: dict) -> list[dict]:
        if results.get("dossier"):
            d = results["dossier"]
            contact = d.get("contact", {})
            stats = d.get("stats", {})
        else:
            contact = results.get("contact", results)
            stats = results.get("stats", {})
        if not isinstance(contact, dict):
            contact = {}
        contact_name = contact.get("name") or contact.get("vendor_name") or results.get("vendor_name") or results.get("vendor") or "Kontakt"
        blocks: list[dict] = [{"block_type": "key_value", "data": {"title": contact_name, "items": [
            {"label": "Kategorie", "value": str(contact.get("category", "\u2014"))},
            {"label": "E-Mail", "value": str(contact.get("email", "\u2014"))},
            {"label": "Gesamtumsatz", "value": self._eur(stats.get("total_revenue", 0))},
            {"label": "Offener Betrag", "value": self._eur(stats.get("open_amount", 0))},
        ]}}]
        dossier = results.get("dossier", {})
        open_items = results.get("open_items", dossier.get("open_items", []) if isinstance(dossier, dict) else [])
        if open_items and isinstance(open_items, list):
            cards = [
                {
                    "title": str(op.get("description", "OP")),
                    "subtitle": str(op.get("due_date", "")),
                    "amount": self._eur(op.get("amount", 0)),
                    "badge": {"label": "Ueberfaellig" if op.get("overdue") else "Offen", "color": "error" if op.get("overdue") else "warning"},
                }
                for op in open_items if isinstance(op, dict)
            ]
            if cards:
                blocks.append({"block_type": "card_list", "data": {"items": cards}})
        return blocks

    def _blocks_create_invoice(self, results: dict) -> list[dict]:
        # Pipeline returns content_blocks directly
        if results.get('content_blocks'):
            return results['content_blocks']
        if results.get("form"):
            return [{"block_type": "form", "data": results["form"]}]
        return [{"block_type": "alert", "data": {"severity": "info", "text": "Rechnungsformular wird geladen..."}}]

    def _blocks_send_invoice(self, results: dict) -> list[dict]:
        """Blocks after Freigeben & Senden."""
        if results.get('content_blocks'):
            return results['content_blocks']
        return [{"block_type": "alert", "data": {"severity": "success", "text": results.get("text", "Rechnung versendet.")}}]

    def _blocks_void_invoice(self, results: dict) -> list[dict]:
        """Blocks after Verwerfen."""
        if results.get('content_blocks'):
            return results['content_blocks']
        return []

    def _blocks_edit_invoice(self, results: dict) -> list[dict]:
        """Blocks for edit — return form."""
        return [{"block_type": "alert", "data": {"severity": "info", "text": "Bearbeitungsmodus wird geladen..."}}]

    def _blocks_choose_template(self, results: dict) -> list[dict]:
        """Show the 3 template options as card_list."""
        return [{
            "block_type": "card_list",
            "data": {"items": [
                {
                    "title": "Clean",
                    "subtitle": "Modern und aufgeraeumt — der Standard",
                    "badge": {"label": "Empfohlen", "color": "primary"},
                    "thumbnail_url": "/api/v1/invoice-templates/clean/preview",
                },
                {
                    "title": "Professional",
                    "subtitle": "Klassisch mit Header — fuer Geschaeftskunden",
                    "thumbnail_url": "/api/v1/invoice-templates/professional/preview",
                },
                {
                    "title": "Minimal",
                    "subtitle": "Nur das Noetigste — fuer Freelancer",
                    "thumbnail_url": "/api/v1/invoice-templates/minimal/preview",
                },
            ]}
        }]

    def _blocks_set_template(self, results: dict) -> list[dict]:
        """Confirmation after template selection."""
        if results.get('content_blocks'):
            return results['content_blocks']
        return [{"block_type": "alert", "data": {"severity": "success", "text": results.get("text", "Template geaendert.")}}]

    def _blocks_upload_logo(self, results: dict) -> list[dict]:
        """Blocks for logo upload flow."""
        if results.get('content_blocks'):
            return results['content_blocks']
        return [{"block_type": "alert", "data": {"severity": "info", "text": "Schick mir einfach dein Logo als Bild (PNG, JPG oder SVG)."}}]

    def _blocks_show_export(self, results: dict) -> list[dict]:
        return [{"block_type": "export", "data": {"items": [
            {"label": "DATEV Export", "url": results.get("datev_url", "/api/v1/export/datev"), "format": "EXTF"},
            {"label": "E\u00dcR als PDF", "url": results.get("eur_url", "/api/v1/reports/euer?format=pdf"), "format": "PDF"},
        ]}}]

    def _blocks_export_datev(self, results: dict) -> list[dict]:
        return self._blocks_show_export(results)

    def _blocks_export_eur(self, results: dict) -> list[dict]:
        return self._blocks_show_export(results)

    def _blocks_settings(self, results: dict) -> list[dict]:
        blocks: list[dict] = []
        # User settings
        blocks.append({"block_type": "key_value", "data": {"title": "Benutzer", "items": [
            {"label": "Name", "value": str(results.get("display_name", "\u2014"))},
            {"label": "Theme", "value": str(results.get("theme", "system"))},
            {"label": "Anrede", "value": "Sie" if results.get("formal_address") else "Du"},
        ]}})
        # Business profile (from compliance_gate / frya_business_profile)
        bp = results.get("business_profile")
        if bp and isinstance(bp, dict):
            biz_items = [
                {"label": "Firma", "value": str(bp.get("company_name") or "\u2014")},
                {"label": "Rechtsform", "value": str(bp.get("company_legal_form") or "\u2014")},
                {"label": "Strasse", "value": str(bp.get("company_street") or "\u2014")},
                {"label": "PLZ/Ort", "value": f'{bp.get("company_zip", "")} {bp.get("company_city", "")}'.strip() or "\u2014"},
                {"label": "Steuernummer", "value": str(bp.get("tax_number") or "\u2014")},
                {"label": "USt-IdNr.", "value": str(bp.get("ust_id") or "\u2014")},
                {"label": "IBAN", "value": str(bp.get("company_iban") or "\u2014")},
                {"label": "E-Mail", "value": str(bp.get("company_email") or "\u2014")},
                {"label": "Telefon", "value": str(bp.get("company_phone") or "\u2014")},
                {"label": "Kleinunternehmer", "value": "Ja (\u00a719 UStG)" if bp.get("is_kleinunternehmer") else "Nein"},
            ]
            blocks.append({"block_type": "key_value", "data": {"title": "Geschaeftsprofil", "items": biz_items}})
            # Completeness hint
            completeness = bp.get("profile_completeness")
            if completeness is not None and completeness < 100:
                blocks.append({"block_type": "alert", "data": {
                    "severity": "warning",
                    "text": f"Profil zu {completeness}% vollstaendig. Fehlende Angaben werden bei der naechsten Rechnung abgefragt.",
                }})
        return blocks

    def _blocks_show_settings(self, results: dict) -> list[dict]:
        return self._blocks_settings(results)

    def _blocks_show_case(self, results: dict) -> list[dict]:
        case = results.get("case", results)
        if not isinstance(case, dict):
            return []
        return [{"block_type": "key_value", "data": {"items": [
            {"label": "Vorgang", "value": str(case.get("case_number", case.get("id", "?")))},
            {"label": "Typ", "value": t_doc_type(str(case.get("case_type", "")))},
            {"label": "Vendor", "value": str(case.get("vendor_name", "\u2014"))},
            {"label": "Betrag", "value": self._eur(case.get("total_amount", 0))},
            {"label": "Status", "value": str(case.get("status", "\u2014"))},
        ]}}]

    def _blocks_show_invoices(self, results: dict) -> list[dict]:
        items = results if isinstance(results, list) else results.get("invoices", results.get("items", []))
        if not isinstance(items, list):
            items = []
        if not items:
            return [{"block_type": "alert", "data": {"severity": "info", "text": "Keine Rechnungen gefunden."}}]
        cards = [self._card(i) for i in items[:10]]
        return [{"block_type": "card_list", "data": {"items": cards}}]

    def _blocks_upload(self, results: dict) -> list[dict]:
        return [{"block_type": "alert", "data": {"severity": "info", "text": "Nutze das Bueroklammer-Symbol unten links oder ziehe Dateien in den Chat."}}]

    def _blocks_show_financial_overview(self, results: dict) -> list[dict]:
        return self._blocks_show_finance(results)

    def _blocks_status_overview(self, results: dict) -> list[dict]:
        return self._blocks_show_finance(results)

    # P-12b: New chart intent builders ------------------------------------ #

    def _blocks_show_expense_categories(self, results: dict) -> list[dict]:
        """Pie chart: expenses grouped by SKR03 account category."""
        bookings = results if isinstance(results, list) else results.get("bookings", results.get("items", []))
        if not isinstance(bookings, list):
            bookings = []
        # Group by account category
        _cat_map = {
            '4210': 'Miete', '4200': 'Miete', '4920': 'Telefon/Internet', '4930': 'Telefon/Internet',
            '4530': 'Kfz-Kosten', '4510': 'Kfz-Kosten', '4964': 'IT/Cloud', '4960': 'IT/Cloud',
            '4360': 'Versicherung', '4650': 'Bewirtung', '4670': 'Reisekosten',
            '4900': 'Porto', '4600': 'Werbung', '4855': 'Nebenkosten',
        }
        _colors = ['#F08A3A', '#FFD54F', '#66E07A', '#4FC3F7', '#FF8A80', '#CE93D8', '#A5D6A7', '#FFAB91']
        cats: dict[str, float] = {}
        for b in bookings:
            if not isinstance(b, dict):
                continue
            acct = str(b.get("debit_account", b.get("skr03_soll", "")))[:4]
            cat = _cat_map.get(acct, 'Sonstiges')
            amt = abs(float(b.get("amount", b.get("gross_amount", 0)) or 0))
            cats[cat] = cats.get(cat, 0) + amt
        if not cats:
            return [{"block_type": "alert", "data": {"severity": "info", "text": "Noch keine Ausgaben verbucht."}}]
        series = [{"label": k, "value": round(v, 2), "color": _colors[i % len(_colors)]}
                  for i, (k, v) in enumerate(sorted(cats.items(), key=lambda x: -x[1]))]
        total = sum(s["value"] for s in series)
        return [{"block_type": "chart", "data": {
            "title": "Ausgaben nach Kategorie",
            "chart_type": "pie",
            "center_value": self._eur(total),
            "center_label": "Gesamt",
            "series": series,
        }}]

    def _blocks_show_profit_loss(self, results: dict) -> list[dict]:
        """KPI card + bar chart for profit/loss."""
        s = results.get("summary", results)
        income = float(s.get("total_income", s.get("income", 0)) or 0)
        expenses = float(s.get("total_expenses", s.get("expenses", 0)) or 0)
        profit = income - expenses
        blocks: list[dict] = []
        # KPI card
        blocks.append({"block_type": "chart", "data": {
            "title": "Gewinn / Verlust",
            "chart_type": "kpi",
            "kpi_value": self._eur(profit),
            "kpi_label": "Ergebnis " + str(s.get("year", "2026")),
            "kpi_trend": "up" if profit > 0 else "down",
            "series": [
                {"label": "Einnahmen", "value": round(income, 2), "color": "#66E07A"},
                {"label": "Ausgaben", "value": round(expenses, 2), "color": "#FF8A80"},
            ],
        }})
        return blocks

    def _blocks_show_revenue_trend(self, results: dict) -> list[dict]:
        """Line chart: revenue by month."""
        bookings = results if isinstance(results, list) else results.get("bookings", results.get("items", []))
        if not isinstance(bookings, list):
            bookings = []
        months: dict[str, float] = {}
        _month_names = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
        for b in bookings:
            if not isinstance(b, dict):
                continue
            d = str(b.get("booking_date", ""))
            if len(d) >= 7:
                m_key = d[:7]  # "2026-03"
                try:
                    m_idx = int(m_key.split('-')[1]) - 1
                    m_label = _month_names[m_idx] if 0 <= m_idx < 12 else m_key
                except (IndexError, ValueError):
                    m_label = m_key
                amt = float(b.get("amount", b.get("gross_amount", 0)) or 0)
                if amt > 0:  # Only income
                    months[m_label] = months.get(m_label, 0) + amt
        if not months:
            return [{"block_type": "alert", "data": {"severity": "info", "text": "Noch keine Umsatzdaten vorhanden."}}]
        series = [{"label": k, "value": round(v, 2), "color": "#F08A3A"} for k, v in months.items()]
        return [{"block_type": "chart", "data": {
            "title": "Umsatzentwicklung",
            "chart_type": "line",
            "series": series,
        }}]

    def _blocks_show_forecast(self, results: dict) -> list[dict]:
        """Forecast: actual + projected for remaining months."""
        s = results.get("summary", results)
        income = float(s.get("total_income", s.get("income", 0)) or 0)
        expenses = float(s.get("total_expenses", s.get("expenses", 0)) or 0)
        from datetime import date
        current_month = date.today().month
        if current_month < 1:
            current_month = 1
        avg_monthly_income = income / current_month if current_month > 0 else 0
        avg_monthly_expense = expenses / current_month if current_month > 0 else 0
        projected_income = income + avg_monthly_income * (12 - current_month)
        projected_expenses = expenses + avg_monthly_expense * (12 - current_month)
        projected_profit = projected_income - projected_expenses

        blocks: list[dict] = []
        # KPI: projected annual profit
        blocks.append({"block_type": "chart", "data": {
            "title": "Jahreshochrechnung",
            "chart_type": "kpi",
            "kpi_value": self._eur(projected_profit),
            "kpi_label": "Hochgerechneter Jahresgewinn",
            "kpi_trend": "up" if projected_profit > 0 else "down",
            "series": [
                {"label": "Einnahmen (hochger.)", "value": round(projected_income, 2), "color": "#66E07A"},
                {"label": "Ausgaben (hochger.)", "value": round(projected_expenses, 2), "color": "#FF8A80"},
                {"label": "Einnahmen (bisher)", "value": round(income, 2), "color": "#A5D6A7"},
                {"label": "Ausgaben (bisher)", "value": round(expenses, 2), "color": "#FFAB91"},
            ],
        }})
        return blocks

    def _blocks_small_talk(self, results: dict) -> list[dict]:
        return []

    def _blocks_unknown(self, results: dict) -> list[dict]:
        return []

    # ------------------------------------------------------------------ #
    #  Actions                                                            #
    # ------------------------------------------------------------------ #

    def _build_actions(
        self, intent: str, results: dict, state: dict | None = None
    ) -> list[dict]:
        # APPROVE with confirmed approval (user clicked Freigeben button)
        if intent == "APPROVE" and results.get("approved"):
            # Approval was executed — show next item or success + context suggestions
            if results.get("next_item"):
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
            return list(self.CONTEXT_SUGGESTIONS.get("APPROVE", self.FALLBACK_SUGGESTIONS))

        # APPROVE without confirmed approval — show item for review with buttons
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
                    "label": "Korrigieren",
                    "chat_text": f"{ni.get('vendor', '')} korrigieren",
                    "style": "secondary",
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

        # SHOW_INBOX with items — Abarbeiten starts review, does NOT auto-approve
        if intent == "SHOW_INBOX" and results.get("items"):
            first = results["items"][0]
            return [
                {
                    "label": "Abarbeiten",
                    "chat_text": "Inbox abarbeiten",
                    "style": "primary",
                    "quick_action": {
                        "type": "show_inbox",
                        "params": {"case_id": first.get("case_id", "")},
                    },
                },
                {
                    "label": "Nur dringende",
                    "chat_text": "Nur dringende Belege",
                    "style": "secondary",
                },
            ]

        # Use CONTEXT_SUGGESTIONS matrix for all other intents
        # Also handle SHOW_SETTINGS alias
        lookup_intent = intent if intent != "SHOW_SETTINGS" else "SETTINGS"
        suggestions = self.CONTEXT_SUGGESTIONS.get(lookup_intent)
        if suggestions:
            return list(suggestions)
        return list(self.FALLBACK_SUGGESTIONS)

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
