# FRYA — Architektur-Entscheidungen (Maze muss entscheiden)

**Datum:** 26.03.2026

---

## 1. GDPR-Endpoints: Pfad-Mismatch

**Problem:** Die UI ruft `/api/v1/gdpr/export` und `/api/v1/gdpr/delete` auf (LegalPage.tsx).
Das Backend hat diese unter `/api/tenant/{tenant_id}/export` und `/api/tenant/{tenant_id}/delete`.

**Optionen:**
- A) UI anpassen auf den Backend-Pfad (braucht tenant_id aus dem JWT)
- B) Backend: Alias-Routes unter /api/v1/gdpr/ erstellen die tenant_id aus dem JWT lesen
- C) Customer-API erweitern (customer_api.py) mit /gdpr/export und /gdpr/delete

**Empfehlung:** Option C — passt zum Muster der anderen Customer-API Endpoints.

---

## 2. Passwort-Änderung: Endpoint fehlt

**Problem:** ProfilePage hat ein "Passwort ändern" Formular, aber kein Backend-Endpoint `/api/v1/auth/change-password` existiert.

**Optionen:**
- A) Endpoint in auth/router.py erstellen
- B) Customer-API erweitern
- C) Feature deaktivieren bis Post-Alpha

**Empfehlung:** Option A — einfacher Endpoint: verify old password, hash new password, update DB.

---

## 3. Material Symbols Woff2: 5.2 MB

**Problem:** Die Material Symbols Rounded Font-Datei ist 5.2 MB. Das ist der größte Asset im Build.

**Optionen:**
- A) Subset der Icons (nur die ~40 verwendeten) mit fonttools extrahieren → ~50 KB
- B) Auf SVG-Icons umsteigen (z.B. @mdi/react)
- C) Akzeptieren — nach erstem Load gecached (30d Cache-Header in Nginx)

**Empfehlung:** Option C für Alpha, Option A für Production.

---

## 4. Upload: Chat-Integration

**Problem:** Upload-Fortschritt wird nicht im Chat angezeigt. Der Upload geht direkt über REST, ohne Frya-Kommentar.

**Optionen:**
- A) Nach Upload ein WS-Event senden das Frya kommentiert
- B) Upload-Status als System-Message im Chat einfügen
- C) Für Alpha so lassen (Chat + Upload sind getrennte Workflows)

**Empfehlung:** Option C für Alpha, Option B für Beta.
