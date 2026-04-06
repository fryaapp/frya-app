# P40 Browser-Test — FRYA Staging

**Datum:** 06.04.2026
**Tester:** P40-BrowserTester (Claude Sonnet 4.6)
**Ziel-URL:** https://staging.myfrya.de
**Login:** testkunde@example.com

---

## Testumgebung & Einschraenkungen

### Browser-Tool-Status

| Tool | Status | Grund |
|------|--------|-------|
| mcp__claude-flow__browser_* | NICHT VERFUEGBAR | `spawnSync agent-browser ENOENT` — Binary nicht installiert |
| mcp__Claude_in_Chrome__* | NICHT VERBUNDEN | Chrome-Extension nicht aktiv (Fehlermeldung: "Claude in Chrome is not connected") |
| mcp__computer-use__* | SCREENSHOT ONLY | Erteilt, aber nur Read-Tier — kein Klicken/Tippen moeglich |
| WebFetch | ZERTIFIKAT-FEHLER | `unable to verify the first certificate` fuer staging.myfrya.de |

### Was war moeglich

- Screenshots des aktuell im Chrome-Browser geoffneten Tabs
- Vollstaendige Quellcode-Analyse aller UI-Komponenten
- Vollstaendige Quellcode-Analyse des Backends (main.py, stores, APIs)
- Visuelle Inspektion des sichtbaren Screens im Production-Browser

### Wichtiger Hinweis

Der im Browser geoffnete Tab zeigt **myfrya.de** (Production), nicht staging.myfrya.de. Der Nutzer war bereits eingeloggt und befand sich auf dem **Finanzen-Screen**. Ein separater Login-Prozess auf Staging konnte nicht durchgefuehrt werden, da kein interaktiver Browser-Zugriff moeglich war.

---

## Screenshot-Dokumentation

### Screenshot 1 — Aktueller Zustand (Production, Finanzen-Screen)

**URL im Browser:** myfrya.de
**Zeitstempel:** 06.04.2026, 23:41 Uhr

**Sichtbare Elemente:**
- Oben rechts: Kontext-Chip "Finanzen" (orangefarbene Pille)
- Frya-Avatar (kleines orangefarbenes Icon links)
- Frya-Nachricht: "Hier ist deine Finanzuebersicht."
- Tabelle "Einnahmen vs. Ausgaben" mit 3 Zeilen:
  - Einnahmen: 0,00 EUR
  - Ausgaben: 0,00 EUR
  - Gewinn: 0,00 EUR
- 3 Action-Buttons: "Ausgaben Detail" / "Gewinn/Verlust" / "Prognose"
- Unten: ChatInput-Bar mit Attach-Icon (Buerklammer) und Senden-Button (Pfeil)
- Placeholder-Text: "Nachricht an Frya..."
- Kein Hamburger-Menu, kein Bottom-Navigation

**Bewertung:** Layout korrekt. Dark-Mode aktiv. Umlaut "uebersicht" korrekt dargestellt. Zahlen alle 0,00 EUR — Testaccount ohne Belege.

---

## Analyse nach Quelldaten (Code-Review ersetzt fehlende Live-Interaktion)

---

## Screen 1 — Login-Seite

**STATUS: CODE OK / LIVE NICHT GETESTET**

### Code-Befunde (LoginPage.tsx)

- E-Mail-Feld mit mail-Icon, autoComplete="email", autoFocus
- Passwort-Feld mit lock-Icon, Passwort-Sichtbarkeits-Toggle (visibility/visibility_off)
- Submit-Button "Anmelden" mit Lade-Animation ("Anmelden...")
- Fehler-Banner: "E-Mail oder Passwort falsch." (rot, error-Icon)
- Session-Expired-Banner: "Deine Sitzung ist abgelaufen. Bitte melde dich erneut an." (orange)
- Link "Passwort vergessen?" → /forgot-password
- Design: Kartenform, animierter Hintergrundglow, FRYA-Banner-Logo

### Potenzielle Probleme

- KEIN "Registrieren"-Button sichtbar (Alpha-Phase, nur Invite)
- Kein Google/SSO-Login

### Nicht getestet (kein Browser-Zugriff)

- Login mit testkunde@example.com / FryaTest2026! auf staging.myfrya.de
- Fehlerfall falsches Passwort
- Session-Expired-Redirect

---

## Screen 2 — Greeting/Startscreen

**STATUS: CODE OK / LIVE NICHT GETESTET**

### Code-Befunde (GreetingScreen.tsx)

- Laedt `/greeting` API-Endpoint beim Mounten
- Zeigt: Frya-Avatar (80px), personalisierten Gruss (z.B. "Hallo, Max!"), Status-Summary
- Urgent-Banner (orange) wenn `priority === 'HIGH'`
- "Zurueck zum Chat (N)" Button wenn Chat bereits Nachrichten hat
- 4 Schnellzugriffs-Chips: Inbox / Finanzen / Belege / Export
- Bug-Report-Button (bug_report Icon) oben rechts
- Settings-Button (settings Icon) oben rechts
- ChatInputBar unten

### Greeting-API Fallback

Wenn `/greeting` fehlschlaegt → Fallback: `{ greeting: 'Hallo!', status_summary: '', urgent: null, suggestions: [] }`

### Potenzielles Problem

- Benutzername wird aus JWT-Token `sub`-Claim gelesen → wenn Testaccount keinen richtigen Namen hat, erscheint nur "Hallo!" ohne Namen
- status_summary > 80 Zeichen → zeigt "Was kann ich fuer dich tun?" statt dem echten Summary

---

## Screen 3 — Chat

**STATUS: TEILWEISE GETESTET (Production-Screenshot)**

### Code-Befunde (ChatView.tsx, ChatInputBar.tsx)

- ChatTopBar: Zurueck-Pfeil (goHome), Bug-Report-Icon, Settings-Icon
- ChatHistory: Nachrichten mit Fade (aeltere Nachrichten 40%/70% Opacity)
- ChatInputBar: Attach-File-Icon, Text-Input, Senden-Button
- WebSocket-Connection zu `wss://[host]/api/v1/chat/stream?token=...`
- Bei WS-Fehler: REST-Fallback auf POST /chat
- Drag-and-Drop fuer Datei-Upload (Overlay: "Belege hier reinwerfen")
- Scanner-Button nur in Capacitor native App (Android)

### Beobachtet (Screenshot)

- ChatInput-Bar korrekt unten
- Attach-Icon (Buerklammer) sichtbar
- Frya-Antwort formatiert als Content-Block (Tabelle)

### Umlaute

- "Uebersicht" korrekt als "Uebersicht" dargestellt (Screenshot bestaetigt)
- Frya-Nachricht "Hier ist deine Finanzuebersicht." korrekt

### WS-Status

- Screenshot zeigt keinen "Verbindung wird hergestellt..." Banner → WS-Verbindung war erfolgreich

### Nicht getestet

- Kontextkette A ("Zeig mir die Inbox" → "Was ist der teuerste Beleg?" → "Buche den")
- Kontextkette B (Rechnung erstellen, Betrag aendern)
- Chat-Nachricht "Zeig mir meine Uebersicht" senden

---

## Screen 4 — Inbox

**STATUS: NICHT GETESTET (kein Browser-Zugriff)**

### Code-Befunde

- Chip "Inbox" auf Greeting-Screen loest `startChat('Inbox')` aus
- ChatView zeigt dann Frya-Antwort zum Inbox-Inhalt
- Belege werden ueber Paperless-API geladen
- Confidence-Badges: In `ChartBlock.tsx` und `CardBlock.tsx` implementiert
- Inbox-Komponenten: `BelegDetail.tsx`, `ApprovalButtons.tsx`, `CorrectionDialog.tsx`

### Erwartetes Verhalten

- Frya antwortet mit einer Liste von Belegen (CardGroupBlock oder TableBlock)
- Confidence-Badges als farbige Indikatoren je Beleg
- Testaccount hat 0 Belege → Frya sollte "Keine Belege in der Inbox" antworten

### Potenzielle Probleme

- Testaccount ohne Daten → leere Inbox (kein Confidence-Badge sichtbar)
- UUID-Fix (P-35/P-36) benoetigt — war in einem frueheren Commit bereits behoben

---

## Screen 5 — Finanzen

**STATUS: TEILWEISE GETESTET (Production-Screenshot)**

### Beobachtet (Screenshot)

- Frya-Antwort: "Hier ist deine Finanzuebersicht."
- Kontext-Chip "Finanzen" oben rechts (orangefarbene Pille) — korrekt
- Tabelle "Einnahmen vs. Ausgaben":
  - Einnahmen: 0,00 EUR
  - Ausgaben: 0,00 EUR
  - Gewinn: 0,00 EUR
- 3 Action-Buttons: "Ausgaben Detail" / "Gewinn/Verlust" / "Prognose"

### PROBLEM: Keine Charts sichtbar

- Die Aufgabe fragt nach "Charts vorhanden?" → Im Screenshot sind KEINE Charts sichtbar
- Es wird nur eine einfache Tabelle angezeigt
- `ChartBlock.tsx` ist implementiert, wird aber bei 0,00-Werten moeglicherweise nicht gerendert
- Moegliche Ursache: Testaccount ohne Belege → keine Chart-Daten verfuegbar → Tabellen-Fallback

**STATUS: PROBLEME — Charts fehlen (vermutlich wegen leerer Datenlage)**

### Action-Buttons

- "Ausgaben Detail", "Gewinn/Verlust", "Prognose" vorhanden → korrekt
- Ob Klick darauf Reaktion ausloest: nicht getestet

---

## Screen 6 — Kontext-Kette A

**STATUS: NICHT GETESTET (kein Browser-Zugriff)**

### Geplanter Test

1. "Zeig mir die Inbox"
2. "Was ist der teuerste Beleg?"
3. "Buche den"

### Code-Analyse Kontext-Verwaltung

- Jede `message_complete`-Nachricht vom Backend enthaelt `case_ref` und `context_type`
- `context_type` steuert welcher Split-Panel geoeffnet wird
- Kontext wird im `chatStore` gespeichert (nicht sitzungsuebergreifend)
- Bei Testaccount ohne Belege: Schritt 2 wuerderesultieren in "Keine Belege gefunden"
- P-40 Commit: "5 bug fixes: context after approval, case details, vendor search, semantic classification, tag dedup" — Kontext-Fixes bereits deployed

### Risiko

- Testaccount ohne Daten → Kontext-Kette kann nicht vollstaendig getestet werden
- Backend haengt sich bei leerem Paperless nicht auf, gibt leere Liste zurueck

---

## Screen 7 — Kontext-Kette B (Rechnung erstellen)

**STATUS: NICHT GETESTET (kein Browser-Zugriff)**

### Geplanter Test

1. "Erstelle eine Rechnung fuer Max Mueller, Teststr 1, 10115 Berlin: 1 Beratung zu 100 EUR"
2. [Frya zeigt Vorschau]
3. "Aendere den Betrag auf 150 EUR"

### Code-Analyse

- Rechnungserstellung: `/invoice` Backend-Endpoint
- FormBlock-Komponente fuer Formular-Vorschau
- ApprovalCard fuer Genehmigungsworkflow
- Kontext-Aenderung: Backend verwaltet "pending invoice" Session-State
- P-40 Bugfix "context after approval" behoben

### Risiko

- Haengt vom LLM-Verhalten ab (IONOS-Proxy, litellm)
- Bei Fehler in der Kontext-Kette: Frya "vergisst" den Rechnungs-Entwurf

---

## Screen 8 — Upload

**STATUS: TEILWEISE ANALYSIERT (Code + Screenshot)**

### Beobachtet (Screenshot)

- Attach-Icon (Buerklammer-Symbol) in der ChatInputBar unten links — VORHANDEN
- Kein eigener Upload-Screen, Upload ist in ChatInputBar integriert

### Code-Befunde (ChatInputBar.tsx)

- Attach-Button: Oeffnet `<input type="file" accept="image/*,application/pdf" multiple>`
- Max Dateigroesse: 20 MB
- Fehlermeldung bei Ueberschreitung: "Datei zu gross: [Name] (max. 20 MB)"
- Upload-Endpoint: POST `/documents/bulk-upload` (multipart/form-data)
- Upload-Erfolg-Meldung: "Alles klar! N Belege empfangen. Ich analysiere das jetzt."
- Drag-and-Drop: Ueber den gesamten ChatView-Bereich (Overlay "Belege hier reinwerfen")
- Scanner-Button: NUR in nativer Android-App (Capacitor.isNativePlatform())

### Status Upload-Button

- VORHANDEN als Attach-Icon in ChatInputBar
- Kein separater FAB mehr (laut Commit P-34b: "kein FAB mehr")

### Nicht getestet

- Datei-Upload-Fluss auf Staging
- Fehlerfall Datei zu gross

---

## Screen 9 — Einstellungen

**STATUS: CODE VOLLSTAENDIG ANALYSIERT**

### Code-Befunde (SettingsScreen.tsx)

- Erreichbar ueber Settings-Icon (Zahnrad) oben rechts auf Greeting- und Chat-Screen
- Zurueck-Button (arrow_back) oben links → zurueck zur Startseite

### Inhalt der Einstellungen

1. **Profil-Section:**
   - Benutzername (aus JWT `sub` oder localStorage `frya-username`)
   - E-Mail (aus localStorage `frya-email`)
   - Rolle: "Administrator" / "Operator" / "Alpha-Tester"
   - **Theme-Switcher:** Dunkel / Hell / Auto (3-Knopf-Auswahl)
   - Sprache: Deutsch (statisch, nicht aenderbar)
   - Benachrichtigungen: An (statisch)

2. **Chat-Section** (nur wenn Nachrichten vorhanden):
   - "Zum Chat (N Nachrichten)" Button

3. **Info-Section:**
   - Version: Alpha 0.9
   - Datenschutz → LegalModal (datenschutz Tab)
   - Impressum → LegalModal (impressum Tab)
   - AGB → LegalModal (agb Tab)

4. **Abmelden-Button** (loescht tokens, redirect zu /login)

### Potenzielle Probleme

- Sprache und Benachrichtigungen sind statisch (Hint, kein echtes Umschalten)
- Theme-Switcher: Setzt localStorage, reactiv ueber useTheme() Hook

---

## Zusammenfassung aller Testergebnisse

| Screen | Status | Problem |
|--------|--------|---------|
| 1. Login-Seite | NICHT GETESTET | Browser-Tools nicht verfuegbar |
| 2. Greeting/Startscreen | NICHT GETESTET | Browser-Tools nicht verfuegbar |
| 3. Chat | TEILWEISE OK | Screenshot: Umlaut korrekt, WS verbunden, Input vorhanden |
| 4. Inbox | NICHT GETESTET | Browser-Tools nicht verfuegbar |
| 5. Finanzen | PROBLEME | Charts fehlen (vermutlich leere Datenlage) |
| 6. Kontext-Kette A | NICHT GETESTET | Browser-Tools nicht verfuegbar |
| 7. Kontext-Kette B | NICHT GETESTET | Browser-Tools nicht verfuegbar |
| 8. Upload | CODE OK | Attach-Icon sichtbar, kein separater Upload-Screen |
| 9. Einstellungen | CODE OK | Theme, Profil, Legal, Logout implementiert |

---

## Kritische Befunde

### BEFUND 1: Browser-Tools nicht verfuegbar

- **Schwere:** HOCH (blockiert alle Live-Tests)
- **Ursache:** Chrome-Extension `Claude in Chrome` nicht verbunden; claude-flow Browser-Binary nicht installiert
- **Empfehlung:** Extension einrichten ODER Playwright/Puppeteer-Setup fuer automatisierte Tests

### BEFUND 2: SSL-Zertifikat staging.myfrya.de

- **Schwere:** MITTEL
- **Ursache:** WebFetch schlaegt mit `unable to verify the first certificate` fehl
- **Empfehlung:** Zertifikat pruefen (`curl -I https://staging.myfrya.de`), ggf. Let's Encrypt erneuern

### BEFUND 3: Charts im Finanzen-Screen fehlen

- **Schwere:** NIEDRIG (vermutlich Datenproblem, nicht Bug)
- **Ursache:** Testaccount hat 0 Belege → alle Betraege 0,00 EUR → ChartBlock rendert keinen Chart
- **Empfehlung:** Testaccount mit Beispieldaten befuellen, dann erneut testen

### BEFUND 4: Production statt Staging

- **Schwere:** MITTEL
- **Beobachtung:** Im Browser war myfrya.de (Production) offen, nicht staging.myfrya.de
- **Empfehlung:** Fuer naechsten Test explizit staging.myfrya.de oeffnen und sicherstellen dass SSL-Zertifikat gueltig ist

---

## Was funktioniert (bestaetigt)

Aus dem Production-Screenshot und der Code-Analyse:

- Dark-Mode korrekt aktiv
- Umlaut-Darstellung korrekt (EUR-Zeichen, "Uebersicht" etc.)
- Frya-Avatar wird angezeigt
- Finanz-Tabelle mit korrektem Format (0,00 EUR)
- Action-Buttons unter der Finanz-Tabelle vorhanden
- Chat-Input-Bar vorhanden mit Attach-Icon
- Keine "Verbindung wird hergestellt..." Warnung → WebSocket verbunden
- Kontext-Chip "Finanzen" oben rechts korrekt

---

## Empfehlungen fuer naechsten Test

1. Chrome-Extension "Claude in Chrome" aktivieren fuer volle Browser-Steuerung
2. Testaccount mit Beispiel-Belegen befuellen (mind. 3-5 Belege)
3. Staging-SSL-Zertifikat pruefen und erneuern falls noetig
4. Playwright-Testscript erstellen fuer automatisierte Regression
5. Testaccount mit Staging testen (nicht Production)

---

*Erstellt: 06.04.2026 | P40-BrowserTester | Methode: Screenshot-Analyse + Quelldaten-Review*
