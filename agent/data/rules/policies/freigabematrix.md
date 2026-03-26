# FRYA Freigabematrix (Release Approval Matrix)

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Freigabe-Modi für alle Aktionen

---

## 1. Zweck

Definiert für jede Aktion im System den Standard-Freigabemodus und die Bedingungen für Eskalation oder Automatisierung.

## 2. Freigabe-Modi

| Modus | Bedeutung |
|-------|-----------|
| AUTO | Automatisch ausgeführt, Audit-Eintrag erzeugt |
| PROPOSE_ONLY | Vorschlag an Nutzer, keine Ausführung ohne Bestätigung |
| REQUIRE_USER_APPROVAL | Blockiert bis explizite Nutzerfreigabe |
| BLOCK_ESCALATE | Immer blockiert, Problemfall erzeugt |

## 3. Universelle Eskalationsregeln

3.1. Confidence unter konfiguriertem Schwellenwert → Modus +1 Stufe.

3.2. Pflichtdaten fehlen → Blockiert unabhängig vom Modus.

3.3. Konflikt erkannt → Modus +1 Stufe.

3.4. Irreversible finanzielle Aktion → Mindestmodus PROPOSE_ONLY (AUTO nur bei expliziter Workflow-Regel).

3.5. Lösch-/Stornovorgang → Mindestmodus REQUIRE_USER_APPROVAL.

3.6. Nutzer kann Standardmodus dauerhaft überschreiben (wird als Konfiguration gespeichert + Audit-Eintrag).

## 4. Aktionen-Matrix

### §4.1 Dokumenttyp erkennen
Standard: AUTO. Begründung: Reversibel, kein finanzieller Impact.

### §4.2 Tags setzen
Standard: AUTO. Begründung: Reversibel, organisatorisch.

### §4.3 Korrespondent zuweisen
Standard: AUTO. Begründung: Reversibel, basiert auf Extraktion.

### §4.4 OCR-Nachanalyse anstoßen
Standard: AUTO. Begründung: Keine Zustandsänderung, nur Neuanalyse.

### §4.5 Bill/Invoice-Draft in Akaunting anlegen
Standard: PROPOSE_ONLY. Bedingung für AUTO: Explizite Workflow-Regel + Confidence ≥ Schwelle + wiederkehrender Beleg. Risiko: Draft in Akaunting erzeugt, noch nicht finalisiert.

### §4.6 Buchung finalisieren
Standard: REQUIRE_USER_APPROVAL. Bedingung für PROPOSE_ONLY: Explizite Workflow-Regel + bekannter Beleg + Confidence ≥ Schwelle. Nie AUTO ohne Workflow-Regel. Risiko: Irreversible finanzielle Aktion.

### §4.7 Zahlungsvorschlag erstellen
Standard: PROPOSE_ONLY. Bedingung für AUTO: Explizite Workflow-Regel + wiederkehrender Beleg + Betrag ≤ Schwelle. Risiko: Vorstufe zur Zahlung.

### §4.8 Zahlung buchen / ausführen
Standard: BLOCK_ESCALATE. IMMER. Keine Ausnahme. Kein AUTO, kein PROPOSE_ONLY. Risiko: Irreversibler Geldfluss.

### §4.9 Dokument als erledigt markieren
Standard: PROPOSE_ONLY. Bedingung für AUTO: Alle Buchungen finalisiert + keine offenen Konflikte.

### §4.10 Wiedervorlage anlegen
Standard: AUTO. Begründung: Reversibel, organisatorisch.

### §4.11 Reminder senden
Standard: PROPOSE_ONLY. Bedingung für AUTO: Interne Erinnerung (nur an Operator). An externe Partei: Mindestens PROPOSE_ONLY.

### §4.12 Problemfall erzeugen
Standard: AUTO. Begründung: Defensiv, erzeugt nur Sichtbarkeit.

### §4.13 Menschenlesbare Prüfsicht erzeugen
Standard: AUTO. Begründung: Read-only, kein Seiteneffekt.

### §4.14 Wiederkehrenden Beleg als Entwurf anlegen
Standard: PROPOSE_ONLY. Bedingung für AUTO: Beleg wurde ≥3x mit gleichem Muster gebucht.

### §4.15 Korrekturfall markieren
Standard: AUTO. Begründung: Defensiv, keine finanzielle Wirkung.

### §4.16 Dokument löschen
Standard: REQUIRE_USER_APPROVAL. IMMER. Keine Ausnahme. GoBD-Compliance: Dokumente dürfen nicht gelöscht werden.

### §4.17 Regel/Policy ändern
Standard: REQUIRE_USER_APPROVAL. IMMER. Keine Ausnahme.

### §4.18 Side-Effect/Workflow ausführen
Standard: REQUIRE_USER_APPROVAL. Bedingung für PROPOSE_ONLY: Explizite Workflow-Regel.

## 5. Übersichtstabelle

| # | Aktion | Standard | Nie AUTO? |
|---|--------|----------|-----------|
| 1 | Dokumenttyp erkennen | AUTO | — |
| 2 | Tags setzen | AUTO | — |
| 3 | Korrespondent zuweisen | AUTO | — |
| 4 | OCR-Nachanalyse | AUTO | — |
| 5 | Bill/Invoice-Draft | PROPOSE_ONLY | — |
| 6 | Buchung finalisieren | REQUIRE_USER_APPROVAL | Ohne Regel: Ja |
| 7 | Zahlungsvorschlag | PROPOSE_ONLY | — |
| 8 | Zahlung ausführen | BLOCK_ESCALATE | **IMMER** |
| 9 | Dokument erledigt | PROPOSE_ONLY | — |
| 10 | Wiedervorlage | AUTO | — |
| 11 | Reminder senden | PROPOSE_ONLY | — |
| 12 | Problemfall erzeugen | AUTO | — |
| 13 | Prüfsicht erzeugen | AUTO | — |
| 14 | Wiederkehrender Entwurf | PROPOSE_ONLY | — |
| 15 | Korrekturfall markieren | AUTO | — |
| 16 | Dokument löschen | REQUIRE_USER_APPROVAL | **IMMER** |
| 17 | Regel/Policy ändern | REQUIRE_USER_APPROVAL | **IMMER** |
| 18 | Side-Effect ausführen | REQUIRE_USER_APPROVAL | Ohne Regel: Ja |
