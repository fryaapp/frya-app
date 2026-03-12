# FRYA Ausnahme- und Problemfall-Policy

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Problemfälle, Ausnahmen, Korrekturen

---

## 1. Zweck

Diese Policy definiert die verbindlichen Regeln für den Umgang mit Ausnahme- und Problemfällen in Frya. Sie regelt, was bei doppelten Belegen, fehlenden Belegen, Bank-Mismatches, OCR-Fehlern, widersprüchlichen Beträgen, unbekannten Steuerfällen, Korrekturen, Stornos und unklaren Leistungszeiträumen geschieht.

Kein Problemfall darf stillschweigend geglättet, ignoriert oder verworfen werden.

---

## 2. Problemfalltypen

### 2.1. Doppelter Beleg (Duplikat)
Zwei oder mehr Belege mit übereinstimmender oder nahezu übereinstimmender Rechnungsnummer, Kreditor und Betrag.

### 2.2. Fehlender Beleg
Eine Buchung oder ein Vorgang existiert in Akaunting, aber kein zugehöriges Dokument existiert in Paperless. Oder: Ein erwarteter Beleg (z. B. aufgrund wiederkehrender Muster) fehlt.

### 2.3. Bank-Mismatch
Bankbewegung stimmt nicht mit der zugehörigen Buchung überein (Betrag, Datum, Empfänger oder Referenz weichen ab).

### 2.4. OCR-Fehler
OCR-Text enthält offensichtliche Lesefehler, fehlende Felder oder nicht-interpretierbare Zeichen, die für die Verarbeitung relevant sind.

### 2.5. Widersprüchliche Beträge
Brutto, Netto und Steuerbetrag auf dem Beleg stimmen rechnerisch nicht überein. Oder: OCR-erkannte Beträge weichen von Akaunting-Daten ab.

### 2.6. Unbekannter Steuerfall
Steuersatz, Steuerbefreiung oder Steuerart ist aus dem Kontext nicht eindeutig ableitbar. Oder: Ein Sonderfall (Reverse Charge, innergemeinschaftlich, Drittland) wird vermutet, aber nicht bestätigt.

### 2.7. Korrekturfall
Ein bereits finalisierter Vorgang muss nachträglich geändert werden (falsche Kontierung, falscher Betrag, falscher Kreditor).

### 2.8. Stornofall
Ein bereits finalisierter Vorgang muss vollständig rückgängig gemacht werden.

### 2.9. Unklarer Leistungszeitraum
Der Leistungszeitraum ist nicht aus dem Beleg ableitbar, betrifft aber die periodengerechte Zuordnung.

---

## 3. Harte Verbote

3.1. Kein Agent darf einen Problemfall stillschweigend glätten (z. B. einen Betrag anpassen, um eine Differenz aufzulösen).

3.2. Kein Agent darf einen doppelten Beleg automatisch verwerfen oder zusammenführen.

3.3. Kein Agent darf einen fehlenden Beleg durch eine Annahme ersetzen.

3.4. Kein Agent darf einen OCR-Fehler automatisch korrigieren und die Korrektur als Fakt behandeln.

3.5. Kein Agent darf widersprüchliche Beträge stillschweigend auflösen.

3.6. Kein Agent darf einen Steuerfall annehmen, der nicht durch explizite Kontextdaten gestützt ist.

3.7. Kein Agent darf eine Stornierung oder Korrektur ohne Audit-Eintrag durchführen.

3.8. Kein Agent darf einen Problemfall schließen, ohne dass die Auflösungsbedingung dokumentiert ist.

3.9. Kein Agent darf einen Problemfall aus dem Log entfernen.

3.10. Kein Agent darf bei einem Problemfall fortfahren, als wäre kein Problem vorhanden.

---

## 4. Pflicht zum Problemfall-Log

4.1. Für jeden erkannten Problemfall wird ein Problemfall-Eintrag in PostgreSQL erzeugt.

4.2. Der Problemfall-Eintrag wird automatisch angelegt (AUTO gemäß Freigabematrix). Keine Verzögerung, kein Vorschlag.

4.3. Jeder Problemfall-Eintrag enthält mindestens:

| Feld | Pflicht | Beschreibung |
|---|---|---|
| problem_case_id | Ja | Eindeutige ID |
| created_at | Ja | Zeitstempel UTC |
| problem_type | Ja | Typ gemäß Abschnitt 2 (DUPLICATE, MISSING_DOCUMENT, BANK_MISMATCH, OCR_ERROR, AMOUNT_CONFLICT, TAX_UNKNOWN, CORRECTION, CANCELLATION, UNCLEAR_PERIOD) |
| case_id | Ja | Referenz auf den betroffenen Fall |
| document_id | Wenn vorhanden | Referenz auf Paperless-Dokument |
| booking_id | Wenn vorhanden | Referenz auf Akaunting-Buchung |
| description | Ja | Menschenlesbare Beschreibung des Problems |
| detected_by | Ja | Agent-ID oder Workflow-ID, der das Problem erkannt hat |
| severity | Ja | BLOCKER oder WARNING |
| status | Ja | OPEN, ESCALATED, RESOLVED, CLOSED |
| resolution | Wenn gelöst | Beschreibung der Auflösung |
| resolved_by | Wenn gelöst | Nutzer-ID oder Agent-ID |
| resolved_at | Wenn gelöst | Zeitstempel UTC |
| related_problems | Wenn vorhanden | Referenzen auf verwandte Problemfälle |
| audit_refs | Ja | Referenzen auf zugehörige Audit-Einträge |

4.4. Problemfälle mit Severity BLOCKER stoppen den Folgeworkflow für den betroffenen Fall.

4.5. Problemfälle mit Severity WARNING stoppen den Workflow nicht, werden aber in jeder Prüfsicht und in jedem Vorschlag referenziert.

---

## 5. Pflicht zum Open Item

5.1. Jeder Problemfall mit Status OPEN oder ESCALATED erzeugt gleichzeitig einen Open Item in PostgreSQL.

5.2. Der Open Item referenziert den Problemfall und enthält:
- Verantwortlich (Nutzer oder Agent)
- Frist (falls ableitbar)
- Erwartete Aktion

5.3. Kein Open Item darf geschlossen werden, bevor der zugehörige Problemfall gelöst ist.

5.4. Open Items ohne Frist werden bei jeder Nutzerinteraktion als offene Punkte referenziert, bis sie aufgelöst sind.

---

## 6. Eskalationsregeln

### 6.1. Eskalation an Nutzer

Erfolgt bei:
- Duplikat erkannt → Nutzer entscheidet, ob zusammenführen, verwerfen oder beibehalten.
- Fehlender Beleg → Nutzer wird informiert und aufgefordert, Beleg nachzuliefern.
- Bank-Mismatch → Nutzer wird informiert und zur Prüfung aufgefordert.
- OCR-Fehler bei Pflichtfeldern → Nutzer wird aufgefordert, Daten manuell zu bestätigen.
- Widersprüchliche Beträge → Nutzer wird informiert und zur Klärung aufgefordert.
- Unklarer Leistungszeitraum → Nutzer wird aufgefordert, Zeitraum zu bestätigen.

### 6.2. Eskalation an Steuerberater / externen Experten

Erfolgt bei:
- Unbekannter Steuerfall, der auch nach Nutzerklärung nicht auflösbar ist.
- Stornierung mit steuerrechtlicher Relevanz (z. B. Vorsteuerkorrektur).
- Korrekturfall, der einen bereits abgeschlossenen Meldezeitraum betrifft.
- Reverse-Charge- oder innergemeinschaftliche Konstellation, die nicht eindeutig aus dem Kontext ableitbar ist.

### 6.3. Eskalationsformat

Jede Eskalation enthält:
- Problemfall-ID und Case-ID
- Problemtyp und Beschreibung
- Bereits ermittelte Daten
- Konkrete Frage an den Empfänger
- Optionen (falls vorhanden)
- Referenz auf betroffene Dokumente und Buchungen

### 6.4. Eskalationsbeschränkungen

6.4.1. Kein Agent darf eine Eskalation eigenständig auflösen.

6.4.2. Kein Agent darf eine Eskalation wiederholt senden, ohne neue Informationen hinzuzufügen.

6.4.3. Kein Agent darf eine Eskalation an Steuerberater senden, ohne vorher den Nutzer informiert zu haben.

---

## 7. Korrektur- und Stornoregeln

### 7.1. Korrekturen

7.1.1. Korrekturen an finalisierten Buchungen dürfen nicht durch Überschreiben erfolgen. Korrekturen erfolgen durch eine Korrekturbuchung.

7.1.2. Jede Korrektur enthält:
- Referenz auf die Originalbuchung
- Begründung
- Neue Werte
- Zeitstempel
- Freigebender Akteur (Nutzer-ID)
- Audit-Eintrag

7.1.3. Korrekturen erfordern REQUIRE_USER_APPROVAL.

7.1.4. Kein Agent darf eine Korrektur vorschlagen, ohne den Originalzustand und den vorgeschlagenen neuen Zustand explizit gegenüberzustellen.

### 7.2. Stornierungen

7.2.1. Stornierungen sind irreversible Vorgänge. Sie erfordern immer REQUIRE_USER_APPROVAL.

7.2.2. Jede Stornierung enthält:
- Referenz auf den zu stornierenden Vorgang
- Begründung
- Zeitstempel
- Freigebender Akteur (Nutzer-ID)
- Audit-Eintrag mit Markierung „STORNO"

7.2.3. Stornierungen, die einen bereits abgeschlossenen Meldezeitraum betreffen, lösen eine Eskalation an Steuerberater aus.

7.2.4. Kein Agent darf eine Stornierung vorschlagen, ohne auf steuerrechtliche Folgewirkungen hinzuweisen (Vorsteuerkorrektur, Umsatzsteuer-Korrektur).

---

## 8. Beispiele

### Beispiel 1: Doppelter Beleg

Situation: Rechnungsnummer RE-2024-0815 von Kreditor X erscheint zweimal in Paperless.
Richtig: Problemfall-Log mit Typ DUPLICATE, Severity WARNING. Open Item an Nutzer: „Duplikat erkannt. Bitte prüfen: zusammenführen, verwerfen oder beibehalten." Kontierungsvorschlag wird nicht blockiert, aber die Warnung wird referenziert.
Falsch: Agent verwirft den zweiten Beleg stillschweigend. Oder: Agent führt beide Belege automatisch zusammen.

### Beispiel 2: Bank-Mismatch

Situation: Bankbewegung zeigt 1.180,00 €. Zugehörige Buchung in Akaunting zeigt 1.190,00 €. Differenz: 10,00 €.
Richtig: Problemfall-Log mit Typ BANK_MISMATCH, Severity BLOCKER. Workflow für diesen Fall wird gestoppt. Open Item an Nutzer mit beiden Werten und Aufforderung zur Klärung.
Falsch: Agent bucht die Differenz stillschweigend auf ein Verrechnungskonto. Oder: Agent passt den Akaunting-Betrag an.

### Beispiel 3: OCR-Fehler

Situation: OCR erkennt Betrag als „1.19O,00 €" (Buchstabe O statt Ziffer 0).
Richtig: Problemfall-Log mit Typ OCR_ERROR, Severity WARNING. Kontierungsvorschlag enthält Markierung „OCR-Unsicherheit bei Betrag". Open Item an Nutzer zur Bestätigung.
Falsch: Agent korrigiert stillschweigend zu „1.190,00 €" und fährt fort ohne Markierung.

### Beispiel 4: Unbekannter Steuerfall

Situation: Beleg enthält den Hinweis „Steuerschuldnerschaft des Leistungsempfängers", aber der Kreditor ist nicht in der EU-Stammdatenliste.
Richtig: Problemfall-Log mit Typ TAX_UNKNOWN, Severity BLOCKER. Eskalation an Nutzer. Wenn Nutzer nicht klären kann: Eskalation an Steuerberater.
Falsch: Agent nimmt Reverse Charge an und kontiert entsprechend ohne Validierung.

### Beispiel 5: Korrekturfall

Situation: Eine finalisierte Buchung wurde auf Konto 6300 gebucht. Der Nutzer meldet, dass Konto 6815 korrekt ist.
Richtig: Problemfall-Log mit Typ CORRECTION. Korrekturbuchung wird vorgeschlagen (REQUIRE_USER_APPROVAL). Originalzustand und neuer Zustand werden gegenübergestellt. Audit-Eintrag wird erzeugt.
Falsch: Agent ändert die bestehende Buchung direkt in Akaunting.

### Beispiel 6: Stornierung mit steuerrechtlicher Wirkung

Situation: Eine finalisierte Rechnung aus Q1 soll in Q2 storniert werden.
Richtig: Problemfall-Log mit Typ CANCELLATION, Severity BLOCKER. Hinweis auf mögliche Vorsteuerkorrektur. Eskalation an Nutzer. Wenn Nutzer bestätigt: Eskalation an Steuerberater vor Ausführung.
Falsch: Agent storniert ohne Hinweis auf periodenübergreifende Wirkung.

### Beispiel 7: Unklarer Leistungszeitraum

Situation: Beleg vom 15.01.2025 für „Jahresabonnement 2025". Leistungszeitraum nicht explizit auf dem Beleg.
Richtig: Problemfall-Log mit Typ UNCLEAR_PERIOD, Severity WARNING. Kontierungsvorschlag enthält Hinweis „Leistungszeitraum nicht explizit – angenommen: 01.01.2025–31.12.2025 (Basis: Beschreibung)". Open Item an Nutzer zur Bestätigung.
Falsch: Agent bucht den vollen Betrag in Januar 2025 ohne Hinweis auf periodengerechte Abgrenzung.
