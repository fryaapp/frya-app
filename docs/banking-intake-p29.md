# Banking Paket 29 — Produktionsnaher Intake-Pfad für Banktransaktionen

Stand: 2026-03-14 | STEP 1+2 verified on staging

## Zusammenfassung

Der SQL-INSERT-Sonderweg ist vollständig abgelöst. Staging-Basis besteht ausschließlich aus
**4 API-konformen Transaktionen** (alle via Akaunting REST API, gültige PM-Codes, `created_from=operator-api-intake-v29*`).

SQL-Altlasten (id=1,2,3, `created_from=staging-seed`, ungültiger PM-Code `offline-payments.transfer.1`)
wurden via Akaunting REST API DELETE entfernt.

---

## Entdeckte Intake-Pfade

### 1. Akaunting REST API — `POST /api/transactions` ✅ LIVE VERIFIZIERT

**Status:** Vollständig funktionsfähig. TRX-2026-004 live erstellt und von Frya korrekt erkannt.

**Endpoint:**
```
POST https://akaunting.staging.myfrya.de/api/transactions?company_id=1
Authorization: Basic <base64(email:password)>
X-Company: 1
Content-Type: application/json
```

**Pflichtfelder:**
| Feld | Typ | Beispiel |
|---|---|---|
| `number` | string | `TRX-2026-004` |
| `type` | `income` / `expense` | `income` |
| `paid_at` | date | `2026-03-14` |
| `amount` | float | `320.0` |
| `currency_code` | string | `EUR` |
| `currency_rate` | float | `1` |
| `account_id` | int | `1` (Bargeld-Konto) |
| `category_id` | int | `2` (Einzahlung) / `4` (Andere) |
| `payment_method` | string | `offline-payments.cash.1` |
| `reference` | string | `INV-2026-003` |
| `description` | string | Freitext |

**Registrierte Payment-Method-Codes (Staging):**
- `offline-payments.cash.1` → "Bargeld"
- `offline-payments.bank_transfer.2` → "Banküberweisung"

**Kritischer Hinweis: company_id-Kontext**
Die Akaunting API-Validierung für `payment_method` benötigt beim Schreiben einen expliziten Company-Kontext.
Ohne `?company_id=1` und `X-Company: 1` Header gibt `Modules::getPaymentMethods('all')` ein leeres Array zurück
und jede payment_method wird als ungültig abgelehnt (HTTP 422).

**Beispiel-Request (curl):**
```bash
curl -X POST \
  "https://akaunting.staging.myfrya.de/api/transactions?company_id=1" \
  -u "kontakt@schatten-potenzial.de:PASSWORD" \
  -H "X-Company: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "income",
    "number": "TRX-2026-004",
    "paid_at": "2026-03-14",
    "amount": 320.0,
    "currency_code": "EUR",
    "currency_rate": 1,
    "account_id": 1,
    "category_id": 2,
    "payment_method": "offline-payments.cash.1",
    "reference": "INV-2026-003",
    "description": "Eingang Projektpauschale Kramer KG",
    "created_from": "operator-api-intake"
  }'
```

**Verifiziertes Live-Ergebnis:**
- HTTP 201, id=5, number=TRX-2026-004, amount=320, reference=INV-2026-003
- Frya probe: `MATCH_FOUND` (reference=INV-2026-003, amount=320, confidence=70/100, HIGH)
- feed_status.transactions_total=4 (3 SQL-seeded + 1 API-intake)
- Frya CONFIRM: `BANK_RECONCILIATION_CONFIRMED`, bank_write_executed=False, no_financial_write=True

---

### 2. CSV-Import via Akaunting UI — `POST /{company_id}/banking/transactions/import`

**Status:** Route vorhanden, Format dokumentiert. Nicht live-verifiziert (erfordert Browser-Session).

**UI-Pfad:** `Banking > Transaktionen > Importieren`

**Felder:** Identisch zur API (type, number, paid_at, amount, currency_code, account_id, category_id, payment_method, reference, description)

**Hinweis:** Erfordert Akaunting Web-Session (nicht Basic Auth). Für Batch-Imports geeignet.

---

### 3. Akaunting UI Manuelle Erfassung — Einzeltransaktion über Konto-Formular

**Status:** Route vorhanden. Nicht live-verifiziert (erfordert Browser).

**UI-Pfad:** `Banking > Konten > [Konto] > Einnahme erstellen`

**Route:** `GET {company_id}/banking/accounts/{account}/create-income`

Geeignet für Einzelbuchungen durch Operatoren ohne API-Kenntnisse.

---

## SQL-Sonderweg: Status und Abgrenzung

Der alte SQL-INSERT (`INSERT INTO akai_transactions ...`) war **nur für den initialen Live-Beweis** (Paket 26) akzeptabel.

**Warum er kein Produktionspfad ist:**
- Umgeht Akaunting-Validierung (z.B. payment_method-Codes)
- Keine Nachvollziehbarkeit (`created_from = 'staging-seed'`)
- Kein Operator-Workflow
- Keine Audit-Spur in Akaunting

**Die SQL-geseedten Transaktionen (id=1,2,3) verwenden außerdem den ungültigen Code `offline-payments.transfer.1`** — dieser ist nicht in Akaunting registriert und würde bei einer manuellen Erstellung via API/UI abgelehnt.

---

## Frya Read-only Connector: Kein Änderungsbedarf

- `GET /api/transactions` ohne `X-Company`-Header funktioniert korrekt (Akaunting resolved company via first company of user)
- `search_transactions()` und `get_feed_status()` in `accounting_akaunting.py` funktionieren wie gehabt
- Keine Code-Änderungen nötig

---

## Saubere Staging-Basis nach STEP 2 (Stand 2026-03-14)

| id | Nummer | Betrag | Ref | Typ | PM-Code | Quelle |
|---|---|---|---|---|---|---|
| 5 | TRX-2026-004 | 320 EUR | INV-2026-003 | income | offline-payments.cash.1 | operator-api-intake-v29 |
| 6 | TRX-2026-A01 | 1450 EUR | INV-2026-101 | income | offline-payments.bank_transfer.2 | operator-api-intake-v29-step2 |
| 7 | TRX-2026-A02 | 89.90 EUR | OUT-2026-042 | expense | offline-payments.cash.1 | operator-api-intake-v29-step2 |
| 8 | TRX-2026-A03 | 2300 EUR | INV-2026-102 | income | offline-payments.bank_transfer.2 | operator-api-intake-v29-step2 |

Entfernte SQL-Altlasten: id=1 (TRX-2026-001), id=2 (TRX-2026-002), id=3 (TRX-2026-003)
Delete-Methode: `DELETE /api/transactions/{id}?company_id=1` mit `X-Company: 1` (HTTP 204 je Eintrag)

## Pflichtprüfpunkte

- ✅ Kein Bank-Write durch Frya
- ✅ Kein Akaunting-Write durch Frya
- ✅ Keine Zahlung
- ✅ Keine Finalisierung
- ✅ Herkunft jeder TX klar benannt (created_from)
- ✅ SQL-Altlasten id=1,2,3 via Akaunting REST API entfernt
- ✅ Alle verbleibenden TXs mit gültigen PM-Codes
- ✅ feed_status.transactions_total=4 bestätigt
- ✅ Probe MATCH_FOUND auf INV-2026-101 (id=6) + INV-2026-102 (id=8)
- ✅ CONFIRM: bank_write_executed=False, no_financial_write=True
- ✅ REJECT: bank_write_executed=False
- ✅ Inspect JSON klar (bank_reconciliation_review sichtbar)
- ✅ Kein Mischzustand SQL+API mehr
