# Banking Paket 29 — Produktionsnaher Intake-Pfad für Banktransaktionen

Stand: 2026-03-14 | Verified on staging

## Zusammenfassung

Der bisherige Zuführungsweg (direkter SQL-INSERT in `akai_transactions`) ist **kein Produktionspfad**.
Dieser Paket dokumentiert und verifiziert den **ersten echten produktionsnahen Intake-Pfad** über die Akaunting REST API.

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

## Pflichtprüfpunkte

- ✅ Kein Bank-Write durch Frya
- ✅ Kein Akaunting-Write durch Frya
- ✅ Keine Zahlung
- ✅ Keine Finalisierung
- ✅ Herkunft der Transaction klar benannt (`created_from: operator-api-intake-v29`)
- ✅ Produktionsnaher Intake (REST API) klar von SQL-Sonderweg getrennt
- ✅ Audit klar (Frya CONFIRM-Event für TRX-2026-004 live geloggt)
- ✅ Inspect JSON klar (bank_reconciliation_review sichtbar)
- ✅ Feed-Sicht klar (feed_total=4 nach API-Intake)
