# FRYA UI — Known Issues

**Datum:** 26.03.2026
**Version:** P-50

---

## Kritisch

### 1. GDPR-Endpoints: Pfad-Mismatch
- **UI erwartet:** `/api/v1/gdpr/export` und `/api/v1/gdpr/delete`
- **Backend hat:** `/api/tenant/{tenant_id}/export` und `.../delete`
- **Auswirkung:** "Daten exportieren" und "Account löschen" auf der Rechtsseite funktionieren nicht
- **Fix:** Backend muss Alias-Routes unter /api/v1/ erstellen oder UI muss tenant_id aus JWT lesen
- **Workaround:** Funktionen im Backend direkt über Telegram nutzbar

### 2. Passwort-Änderung: Kein Endpoint
- **UI hat:** Passwort-Änderungs-Formular in ProfilePage
- **Backend hat:** Keinen `/api/v1/auth/change-password` Endpoint
- **Auswirkung:** "Passwort ändern" Button zeigt Fehler
- **Fix:** Endpoint im auth-Router erstellen

---

## Mittel

### 3. Upload: Keine 50-File-Limit-Validierung im Frontend
- **Problem:** Der Client limitiert nicht die Anzahl der Dateien beim Bulk-Upload
- **Auswirkung:** Backend gibt 400 zurück, aber die UI zeigt nur generischen Fehler
- **Fix:** Max-Files-Check in Dropzone.tsx vor dem Upload

### 4. Upload: Kein Chat-Kommentar von Frya
- **Problem:** Nach Upload kommentiert Frya nicht im Chat über den Fortschritt
- **Auswirkung:** Upload und Chat sind getrennte Workflows
- **Fix:** WebSocket-Event nach Upload-Abschluss oder System-Message im Chat

### 5. Material Symbols Font: 5.2 MB
- **Problem:** Die Icon-Font-Datei ist 5.2 MB groß
- **Auswirkung:** Erster Seitenaufruf lädt 5.2 MB extra (danach 30d Cache)
- **Fix:** Icon-Subset mit fonttools (~50 KB statt 5.2 MB) — Post-Alpha

---

## Niedrig

### 6. Settings API-Pfad
- **Problem:** SettingsPage nutzt `/api/v1/preferences` korrekt, aber Onboarding nutzt `/api/v1/settings`
- **Auswirkung:** Onboarding-Einstellungen werden nicht gespeichert (stiller Fehler, try/catch)
- **Fix:** OnboardingPage auf /preferences umstellen

### 7. Keine Re-Render-Optimierung
- **Problem:** Keine React.memo() oder useMemo() für teure Komponenten
- **Auswirkung:** Potentiell unnötige Re-Renders (Performance-Impact unklar ohne Profiling)
- **Fix:** Nach Browser-Profiling gezielt optimieren

### 8. Keyboard-Aktivierung auf Cards
- **Problem:** Cards mit onClick haben tabIndex=0 aber jetzt onKeyDown für Enter/Space (gefixt)
- **Auswirkung:** Gefixt — Enter/Space aktiviert klickbare Cards

### 9. Touch-Targets unter 48px
- **Problem:** IconRail Buttons (36px), SplitView Close (32px), ChatInput Icons (40px)
- **Auswirkung:** IconRail ist Desktop-only (kein Touch-Problem). SplitView/ChatInput minimal unter 48px
- **Fix:** Padding auf 48px erhöhen — kosmetisch

---

## Nicht implementiert (Post-Alpha)

- 2FA Setup (Screen 21) — Placeholder vorhanden
- Benachrichtigungen (Screen 22) — Placeholder vorhanden
- Kostenstellen — nicht geplant für Alpha
- CSV-Export — nicht geplant für Alpha
- Onboarding-Flow — existiert als 3-Schritt-Wizard, aber Paperless/Telegram-Verbindung fehlt
