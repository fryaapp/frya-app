# FRYA Exception & Problem Case Policy

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Ausnahmefälle und Problemfälle

---

## 1. Zweck

Regelwerk für den Umgang mit doppelten Belegen, fehlenden Belegen, Bank-Mismatches, OCR-Fehlern, widersprüchlichen Beträgen, unbekannten Steuerfällen, Korrekturen, Stornos und unklaren Leistungszeiträumen.

## 2. Problemfalltypen

| Typ | Beschreibung |
|-----|-------------|
| DUPLICATE | Doppelter Beleg (gleiche Rechnungsnr + Kreditor) |
| MISSING_DOCUMENT | Fehlender Beleg zu einer Buchung |
| BANK_MISMATCH | Bankbewegung passt nicht zur Buchung |
| OCR_ERROR | OCR-Erkennung fehlerhaft oder unvollständig |
| AMOUNT_CONFLICT | Widersprüchliche Beträge |
| TAX_UNKNOWN | Unbekannter/unklarer Steuerfall |
| CORRECTION | Korrektur einer bestehenden Buchung |
| CANCELLATION | Stornierung mit steuerrechtlicher Wirkung |
| UNCLEAR_PERIOD | Unklarer Leistungszeitraum |

## 3. Harte Verbote

3.1. Kein stilles Glätten. Betragsabweichungen dürfen nicht automatisch angepasst werden.

3.2. Kein automatisches Zusammenführen bei Duplikaten. Operator entscheidet.

3.3. Keinen OCR-Fehler als Fakt behandeln.

3.4. Keine Aktion ohne Audit-Eintrag bei Korrekturen oder Stornos.

3.5. Kein Problemfall-Schließen ohne dokumentierte Auflösung.

3.6. Keine eigenständige Entscheidung bei Steuerfragen — bei Unklarheit eskalieren.

## 4. Pflicht zum Problemfall-Log

Bei jedem erkannten Problem sofort AUTO-Eintrag in PostgreSQL (frya_problem_cases):
- problem_id (unique), problem_type, case_id, title, details, severity (BLOCKER/WARNING), exception_type, document_ref, accounting_ref, created_by, created_at.

## 5. Pflicht zum Open Item

5.1. Jeder Problemfall mit Severity BLOCKER erzeugt einen Open Item mit Status WAITING_USER.

5.2. Jeder Problemfall mit Severity WARNING erzeugt einen Open Item mit Status OPEN.

5.3. BLOCKER-Probleme stoppen den Folgeworkflow für den betroffenen Fall.

## 6. Eskalationsregeln

### Stufe 1: Nutzer
- Duplikate → Nutzer entscheidet (zusammenführen oder separate Vorgänge)
- OCR-Fehler → Nutzer prüft Original
- Fehlender Beleg → Nutzer liefert nach
- Betragskonflikt → Nutzer klärt

### Stufe 2: Steuerberater (nach Nutzer-Erstinformation)
- Unbekannter Steuerfall nicht auflösbar
- Stornierung mit steuerrechtlicher Relevanz (periodenübergreifend)
- Korrektur betrifft abgeschlossenen Meldezeitraum
- Reverse Charge / innergemeinschaftlich unklar

## 7. Korrektur- und Stornoregeln

7.1. Korrekturen: Originalzustand bleibt erhalten. Neue Korrekturbuchung mit Referenz auf Original.

7.2. Stornos: Stornobuchung als eigenständiger Vorgang. Originalvorgang wird nicht gelöscht.

7.3. Periodenübergreifende Stornos (z.B. finalisierte Rechnung Q1 wird in Q2 storniert): IMMER Hinweis auf Vorsteuerkorrektur, IMMER Steuerberater-Eskalation vor Ausführung.

## 8. Beispiele

### Duplikat erkannt
Zwei Belege mit gleicher Rechnungsnummer und Kreditor. → Problemfall DUPLICATE, Severity WARNING. Kein automatischer Verwurf. Nutzer entscheidet.

### OCR-Fehler
Betrag "1.2A7,50" statt "1.247,50". → Problemfall OCR_ERROR. Confidence-Cap. Nutzer prüft Original.

### Betragskonflikt
Rechnung 1.000€ netto, aber Bankbewegung 950€. → Problemfall AMOUNT_CONFLICT. Mögliche Erklärung: Skonto. Nutzer klärt.

### Stornierung periodenübergreifend
Rechnung Q1, Storno in Q2. → Problemfall CANCELLATION, Severity BLOCKER. Hinweis Vorsteuerkorrektur. Steuerberater-Eskalation.

### Unklarer Leistungszeitraum
"Jahresabonnement 2026" ohne expliziten Zeitraum. → Problemfall UNCLEAR_PERIOD, Severity WARNING. Angenommen 01.01.-31.12., Nutzer bestätigt.
