# FRYA UI — Testing Results

**Datum:** 26.03.2026
**Branch:** feature/security-fixes-paket-22
**Build:** Vite 8.0.2, React 19, TypeScript 0 Fehler

---

## Phase B: Real-Testing (Code-basiert)

### B.5 — Login
- [x] Login-Seite existiert (LoginPage.tsx)
- [x] Email + Passwort → POST /api/v1/auth/login → Token in localStorage
- [x] Fehlermeldung auf Deutsch: "E-Mail oder Passwort falsch."
- [x] Nach Login: Navigate to "/"
- [x] Refresh-Token: proaktiver Refresh 5 Min vor Ablauf + 401-Retry
- [x] Kein englischer Text sichtbar

### B.6 — Startscreen
- [x] Frya-Avatar + Begrüßung (kompakt, horizontal)
- [x] Begrüßung zeitbasiert: Guten Morgen / Hallo / Guten Abend
- [x] KPI-Grid: Inbox-Count, Einnahmen, Ausgaben, Überfällige Fristen
- [x] Überfällige-Warnung rot hervorgehoben
- [x] Shortcut-Chips klickbar (Inbox, Fristen, Vorgänge)
- [x] Eingabefeld vorhanden (ChatInput)
- [x] Kein Split im Ruhezustand
- [x] BottomNav: 5 Tabs (Start, Inbox, Vorgänge, Fristen, Mehr)
- [x] IconRail: Desktop-only, 52px, nur Icons mit aria-labels
- [x] Theme-Wechsel: hell/dunkel/system via SettingsPage

### B.7 — Split-Animation
- [x] SplitView mit 500ms cubic-bezier Transition
- [x] Oben ~58%, unten ~42%
- [x] Trennung: subtile Linie, kein Slider/Handle
- [x] Close-Button → Split fährt zurück
- [x] CSS-Transition konfiguriert (keine JS-Animation)

### B.8 — Chat + WebSocket
- [x] WebSocket Hook (useWebSocket.ts) mit exponential backoff
- [x] Typing-Indicator (TypingIndicator.tsx)
- [x] Streaming: appendChunk() für Token-für-Token Rendering
- [x] Suggestions-Chips nach Antwort (SuggestionChips.tsx)
- [x] Chip-Klick sendet Text
- [x] Ältere Nachrichten: opacity-40 / opacity-70
- [x] Datei-Upload Button (attach_file Icon)
- [x] Auto-Reconnect mit exponential backoff (1s → 30s max)
- [x] REST-Fallback: POST /api/v1/chat wenn WS disconnected
- [x] Markdown-Rendering (react-markdown) für Frya-Antworten

### B.9 — Inbox
- [x] Lädt von GET /api/v1/inbox
- [x] Cards: Absender, Typ, Betrag, Confidence-Badge
- [x] Confidence-Farben: Sicher=grün, Hoch=blau, Mittel=gelb, Unsicher=rot
- [x] Risk-Flags als Chips mit warning-Icon
- [x] "KI-Vorschlag · bitte prüfen" Label
- [x] REQUIRE_USER_APPROVAL: border-l-error Hervorhebung
- [x] Klick → Navigate zu /inbox/:caseId
- [x] Leere Inbox: "Keine offenen Belege — alles erledigt!"
- [x] Filter-Tabs: Ausstehend / Freigegeben / Abgelehnt

### B.10 — Beleg-Detail + Freigabe
- [x] Thumbnail von /documents/{id}/thumbnail
- [x] Extrahierte Felder (extracted_fields Object)
- [x] Buchungsvorschlag: SKR03 Soll + Haben
- [x] Buttons: Freigeben (filled), Korrigieren (tonal), Ablehnen (text), Später (text)
- [x] Freigeben → POST /approve → Erfolgsmeldung → auto-close
- [x] Korrigieren → CorrectionDialog
- [x] Lern-Scope: Nur diesmal / Immer für Lieferant / Immer für Kategorie / Immer nachfragen
- [x] payment_execute hat keinen Button (filtered in ApprovalCard)

### B.11 — Wäschekorb (Upload)
- [x] Dropzone vorhanden (Dropzone.tsx)
- [x] Drag & Drop + Dateiauswahl
- [x] Bulk-Upload: api.bulkUpload()
- [x] Pipeline-Status: PipelineStatus.tsx mit Dots
- [x] Metric-Cards: Verarbeitet/Vorgänge/Brauchen dich
- [ ] Frya Chat-Kommentar zum Fortschritt — **nicht implementiert** (Upload geht direkt über REST)
- [ ] 50 Files Limit — **client-seitig nicht enforced** (Backend enforced)
- [ ] Duplikat-Erkennung in UI — Status "duplicate" wird angezeigt, aber kein Chat-Dialog

### B.12 — Vorgänge (Cases)
- [x] Lädt von GET /api/v1/cases
- [x] Status-Badges farbcodiert (10 Statuses in StatusBadge)
- [x] Confidence-Badges
- [x] Konflikte als Chips
- [x] Filter-Chips: 8 Optionen (ALL, OPEN, DRAFT, OVERDUE, BOOKED, ANALYZED, PROPOSED, APPROVED)
- [x] Server-Side Filter (re-fetch bei Wechsel)
- [x] Klick → /cases/:caseId → CaseDetail mit Timeline

### B.13 — Fristen
- [x] Lädt von GET /api/v1/deadlines
- [x] Sortiert: Überfällig → Heute → Bald → Skonto
- [x] Farbcodiert: Rot/Gelb/Grün/Blau
- [x] Left-Border an Cards
- [x] Skonto-Fristen erkennbar (eigene Sektion)
- [x] Klickbar: Items mit case_id navigieren zu /cases/:id

### B.14 — Einstellungen + Onboarding + Feedback
- [x] Einstellungen: Theme/Anrede/Emoji/Notifications → PUT /api/v1/preferences/{key}
- [x] Theme-Wechsel sofort (useTheme Hook)
- [x] FAB (Problem-Melden) unten rechts (bug_report Icon)
- [x] FAB → /feedback → Freitext + Screenshot-Upload
- [x] Onboarding: 3 Schritte (Theme, Du/Sie, KI-Disclaimer)
- [x] KI-Disclaimer auf Deutsch

---

## Phase C: Cross-Checks

### C.15 — Kein Englisch
- [x] Alle Buttons auf Deutsch
- [x] Alle Fehlermeldungen auf Deutsch
- [x] Alle Platzhalter auf Deutsch
- [x] Alle Status-Texte auf Deutsch
- [x] Alle Empty-States auf Deutsch
- [x] Toast-Meldungen auf Deutsch ("Gespeichert")
- [x] "Inbox" als akzeptiertes Lehnwort
- [x] "Phase 2" → geändert zu "noch nicht verfügbar"

### C.16 — Kein Modellname
- [x] Kein "Claude", "Sonnet", "Llama", "GPT", "Mistral", "IONOS" in UI
- [x] Kein Modellname im Eingabefeld
- [x] App nutzt "FRYA" und "KI-Vorschlag" konsistent

### C.17 — Mobile Responsiveness
- [x] BottomNav statt IconRail (BottomNav.tsx für Mobile)
- [x] max-w-[80%] auf Chat-Bubbles
- [x] overflow-y-auto auf allen Listen
- [x] Dropzone responsive (w-full)
- [x] SplitView 58%/42% Split

### C.18 — Dark + Light Theme
- [x] M3 Semantic Tokens durchgehend (text-on-surface, bg-surface-container etc.)
- [x] Keine hardcoded text-white/text-black
- [x] Keine Hex-Farben in inline styles
- [x] KPI-Icons: text-success/text-error (semantisch)

### C.19 — Error-States
- [x] API nicht erreichbar → "... konnte nicht geladen werden." (pro Page)
- [x] 401 → Token Refresh → bei Fehlschlag Logout → /login
- [x] ErrorBoundary → "Etwas ist schiefgelaufen" + "Neu laden"
- [x] WebSocket disconnect → "Verbindung wird hergestellt…" Banner
- [x] Leere Inbox → "Keine offenen Belege — alles erledigt!"
- [x] Leere Cases → "Keine Vorgänge gefunden."
- [x] Upload-Fehler → status: 'error' mit Fehlermeldung

### C.20 — Performance
- [x] JS Bundle: 132 KB gzip (< 500 KB Limit)
- [x] Code-Splitting: 15+ Chunks via React.lazy()
- [x] Fonts + Icons self-hosted (kein CDN)
- [x] Lazy-Loading für Thumbnails (IntersectionObserver)
- [ ] Re-Render-Optimierung — **nicht getestet** (braucht Browser DevTools)
- [ ] Memory-Leak-Test — **nicht getestet** (braucht 5 Min Browser-Beobachtung)

---

## Zusammenfassung

| Kategorie | Bestanden | Gesamt | Quote |
|-----------|-----------|--------|-------|
| B.5 Login | 6/6 | 6 | 100% |
| B.6 Start | 10/10 | 10 | 100% |
| B.7 Split | 5/5 | 5 | 100% |
| B.8 Chat | 10/10 | 10 | 100% |
| B.9 Inbox | 10/10 | 10 | 100% |
| B.10 Beleg | 8/8 | 8 | 100% |
| B.11 Upload | 5/8 | 8 | 63% |
| B.12 Cases | 7/7 | 7 | 100% |
| B.13 Fristen | 6/6 | 6 | 100% |
| B.14 Settings | 6/6 | 6 | 100% |
| C.15 Deutsch | 8/8 | 8 | 100% |
| C.16 Modell | 3/3 | 3 | 100% |
| C.17 Mobile | 5/5 | 5 | 100% |
| C.18 Theme | 4/4 | 4 | 100% |
| C.19 Errors | 7/7 | 7 | 100% |
| C.20 Perf | 4/6 | 6 | 67% |
| **GESAMT** | **104/109** | **109** | **95%** |
