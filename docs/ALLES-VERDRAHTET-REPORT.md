# Alles-Verdrahtet Report — 27.03.2026

## Phase A: ActionRouter Services (14/14)

| Handler | Status | Methode |
|---------|--------|---------|
| approve | ✅ | _InboxService.approve → BookingApprovalService.process_response |
| reject | ✅ | _InboxService.reject → BookingApprovalService.process_response(REJECT) |
| defer | ✅ | _InboxService.defer → returns next_item |
| list_pending | ✅ | _InboxService.list_pending → CaseRepository.list_active_cases |
| show_deadlines | ✅ | _DeadlineService.list → deadline_analyst_service.check_all_deadlines |
| show_finance | ✅ | _FinanceService.get_finance_summary → BookingService |
| show_contact.dossier | ✅ | _ContactService.get_dossier → repo.get_contact_by_id + list_bookings |
| show_bookings | ✅ | _BookingService.list → repo.list_bookings |
| show_open_items | ✅ | _OpenItemService.list → repo.list_open_items |
| prepare_form | ✅ | _InvoiceService.prepare_form → build_invoice_form() |
| finalize_invoice | ✅ | _InvoiceService.finalize → returns URL |
| export_datev | ✅ | _FinanceService.export_datev → returns URL |
| show_settings | ✅ | _SettingsService.get → frya_user_preferences |
| update_setting | ✅ | _SettingsService.update → frya_user_preferences upsert |
| mark_private | ✅ | _CaseService.mark_private → metadata.private = true |

**Service-Registry: 14/14 verdrahtet ✅**

## Phase B: Settings + Streaming

- GET /settings: ✅ 200 (`display_name: Maze, theme: system`)
- PUT /settings: ✅ 200 (`status: ok`)
- Text-Streaming: **Geparkt** — Communicator-Pipeline gibt Antwort als ganzen Text zurück. Streaming erfordert Umbau der Pipeline (stream=True in litellm + async generator im WS-Handler). Für MVP nicht blocking.

## Phase C: Multi-Tenant

**Geparkt.** Reason: Der bestehende Invite-Flow über das Operator-Backend (`POST /ui/users/invite`) funktioniert bereits. Ein separater `POST /admin/invite` würde die Logik duplizieren. Die invite-mail wurde in einem früheren Fix repariert (Redis URL Bug). Empfehlung: Für Alpha-Phase den Operator-UI Invite nutzen, Multi-Tenant API als V2-Feature planen.

## Phase D: E2E Tests (via API)

| Test | Ergebnis |
|------|----------|
| Login | ✅ Token erhalten |
| Greeting API | ✅ "Noch fleißig Maze!" |
| Chat (Hallo) | ✅ reply + routing: fast |
| Chat (Inbox = Regex) | ✅ routing: regex |
| Chat (Finanzen = Regex) | ✅ routing: regex, actions: EÜR/DATEV |
| Settings GET | ✅ display_name, theme |
| Settings PUT | ✅ status: ok |
| Hash-Chain | ✅ valid, 25 Buchungen |
| GDPR Export | ✅ ZIP 124 KB |
| Dossier | ✅ Kontakt + Stats |

## Phase E: Bugs

- ✅ Logos komprimiert: Avatar 4.7MB→613KB, Banner 4.2MB→386KB
- ✅ Alte Bundles aufgeräumt: 23→1 JS-Dateien
- ⏳ DNS myfrya.de (ohne www): Manuell in Hetzner DNS-Console zu ändern (anderer Server)

## Hash-Chain
```json
{"valid": true, "total": 25, "errors": []}
```

## Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| agent/app/agents/service_registry.py | Komplett neu: 14/14 Handler implementiert |
| agent/app/api/customer_api.py | GET/PUT /settings Endpoints |
| Server: /opt/frya/ui-dist/ | 22 alte JS-Bundles gelöscht, Logos komprimiert |
