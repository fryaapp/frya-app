# FRYA Freigabematrix

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Freigabematrix für Aktionen

---

## 1. Zweck

Diese Matrix definiert für jede systemrelevante Aktion in Frya den Standard-Freigabemodus, die Bedingungen für automatische Ausführung, Vorschlagsmodus oder Nutzerfreigabe, die Risiken und die Begründung.

---

## 2. Freigabemodi

| Modus | Bedeutung |
|---|---|
| **AUTO** | Aktion wird automatisch ausgeführt. Audit-Eintrag wird erzeugt. Kein Nutzereingriff erforderlich. |
| **PROPOSE_ONLY** | Aktion wird vorbereitet und dem Nutzer als Vorschlag präsentiert. Keine Ausführung ohne explizite Bestätigung. |
| **REQUIRE_USER_APPROVAL** | Aktion wird blockiert, bis der Nutzer explizit freigibt. Fehlende Antwort ist keine Zustimmung. |

---

## 3. Entscheidungsregeln

3.1. Wenn eine Aktion irreversibel ist und finanzielle Daten betrifft, ist der Mindestmodus PROPOSE_ONLY. AUTO ist nur bei expliziter Workflow-Regel zulässig.

3.2. Wenn eine Aktion irreversibel ist und einen Lösch- oder Stornovorgang betrifft, ist der Mindestmodus REQUIRE_USER_APPROVAL.

3.3. Wenn Confidence unter dem konfigurierten Schwellenwert liegt, wird der Modus um eine Stufe angehoben (AUTO → PROPOSE_ONLY, PROPOSE_ONLY → REQUIRE_USER_APPROVAL).

3.4. Wenn Pflichtdaten fehlen, wird die Aktion blockiert, unabhängig vom Standardmodus.

3.5. Wenn ein Konflikt vorliegt (widersprüchliche Daten, Duplikat, Abweichung von Historie), wird der Modus um eine Stufe angehoben.

3.6. Der Nutzer kann pro Aktion den Standardmodus dauerhaft überschreiben. Die Überschreibung wird als Konfiguration gespeichert und im Audit-Log referenziert.

---

## 4. Freigabematrix

### 4.1. Dokumenttyp erkennen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Confidence ≥ Schwellenwert. Dokumenttyp in bekannter Typenliste. |
| Bedingungen PROPOSE_ONLY | Confidence unter Schwellenwert. Dokumenttyp nicht in bekannter Typenliste. |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reversibel) |
| Risiken | Fehlklassifikation führt zu falschem Folgeworkflow. |
| Begründung | Reversible Aktion. Nachkorrektur jederzeit möglich. Audit-Eintrag dokumentiert Erstklassifikation. |

### 4.2. Tags setzen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Tag ableitbar aus Dokumenttyp, Kreditor oder konfigurierter Regel. |
| Bedingungen PROPOSE_ONLY | Tag nicht eindeutig ableitbar. Mehrere plausible Tags. |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reversibel) |
| Risiken | Falsches Tag beeinflusst Filteransichten und Wiedervorlagen. |
| Begründung | Reversibel. Korrektur ändert keine finanziellen Zustände. |

### 4.3. Korrespondent zuweisen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Korrespondent eindeutig aus OCR-Text oder Stammdaten ableitbar. Confidence ≥ Schwellenwert. |
| Bedingungen PROPOSE_ONLY | Mehrere plausible Korrespondenten. Korrespondent nicht in Stammdaten. Confidence unter Schwellenwert. |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reversibel) |
| Risiken | Falsche Zuordnung beeinflusst Kontierungsvorschläge und Dublettenprüfung. |
| Begründung | Reversibel, aber falsche Zuordnung hat Folgewirkung auf Accounting-Pipeline. |

### 4.4. OCR-Nachanalyse anstoßen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | OCR-Qualität unter Schwellenwert. Pflichtfelder nicht erkannt. Konfigurierte Regel existiert. |
| Bedingungen PROPOSE_ONLY | – (nicht vorgesehen) |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reine Leseoperation) |
| Risiken | Zusätzlicher Ressourcenverbrauch. Keine finanziellen Risiken. |
| Begründung | Reine Leseoperation ohne Seiteneffekte. Kein Risiko für finanzielle oder Archivzustände. |

### 4.5. Bill/Invoice-Draft in Akaunting anlegen

| Feld | Wert |
|---|---|
| Standardmodus | PROPOSE_ONLY |
| Bedingungen AUTO | Alle Pflichtfelder vorhanden. Confidence ≥ Schwellenwert. Kreditor in Stammdaten. Keine Duplikat-Warnung. Explizite Workflow-Regel erlaubt AUTO für diesen Belegtyp. |
| Bedingungen PROPOSE_ONLY | Standardfall. Daten vorhanden, aber kein AUTO-Workflow konfiguriert. |
| Bedingungen REQUIRE_USER_APPROVAL | Pflichtdaten fehlen. Duplikat-Warnung. Konflikte mit Historie. Confidence unter kritischem Schwellenwert. |
| Risiken | Fehlerhafter Draft erzeugt inkonsistenten Zustand in Akaunting. Draft ist nicht finalisiert, aber sichtbar. |
| Begründung | Draft ist nicht irreversibel, aber erzeugt Zustand in Akaunting. Mindestens PROPOSE_ONLY, um Datenqualität zu sichern. |

### 4.6. Buchung finalisieren

| Feld | Wert |
|---|---|
| Standardmodus | REQUIRE_USER_APPROVAL |
| Bedingungen AUTO | Nur wenn eine explizite, dokumentierte Automatisierungsregel existiert UND alle Pflichtdaten vorhanden UND Confidence ≥ hoher Schwellenwert UND kein Konflikt UND kein offener Punkt. |
| Bedingungen PROPOSE_ONLY | – (für irreversible finanzielle Aktion nicht ausreichend) |
| Bedingungen REQUIRE_USER_APPROVAL | Standardfall. Immer, außer bei expliziter AUTO-Regel. |
| Risiken | Irreversible finanzielle Änderung. Fehlerhafte Buchung erfordert Stornobuchung. GoBD-Konformität betroffen. |
| Begründung | Höchste Risikostufe. Irreversibel. GoBD-relevant. Default ist Nutzerfreigabe. |

### 4.7. Zahlungsvorschlag erstellen

| Feld | Wert |
|---|---|
| Standardmodus | PROPOSE_ONLY |
| Bedingungen AUTO | Alle Pflichtdaten vorhanden. Fälligkeitsdatum erreicht oder überschritten. Betrag und Empfänger validiert. Explizite Workflow-Regel erlaubt AUTO. |
| Bedingungen PROPOSE_ONLY | Standardfall. |
| Bedingungen REQUIRE_USER_APPROVAL | Betrag über konfigurierter Schwelle. Empfänger nicht in Stammdaten. Abweichung vom üblichen Zahlungsmuster. |
| Risiken | Fehlerhafter Zahlungsvorschlag kann bei AUTO-Freigabe zu falscher Zahlung führen. |
| Begründung | Zahlungsvorschlag selbst ist nicht irreversibel, aber nahe an irreversibler Aktion. Vorsicht geboten. |

### 4.8. Zahlung buchen / ausführen

| Feld | Wert |
|---|---|
| Standardmodus | REQUIRE_USER_APPROVAL |
| Bedingungen AUTO | Nicht vorgesehen. Keine AUTO-Regel für Zahlungsausführung zulässig ohne Ausnahmedefinition auf Systemebene. |
| Bedingungen PROPOSE_ONLY | – (für irreversible finanzielle Aktion nicht ausreichend) |
| Bedingungen REQUIRE_USER_APPROVAL | Immer. |
| Risiken | Irreversibler Geldtransfer. Höchstes Risiko im System. |
| Begründung | Maximales Risiko. Keine Automatisierung im Standardbetrieb. Nutzerfreigabe ist Pflicht. |

### 4.9. Dokument als erledigt markieren

| Feld | Wert |
|---|---|
| Standardmodus | PROPOSE_ONLY |
| Bedingungen AUTO | Alle offenen Punkte für dieses Dokument sind gelöst. Zugehörige Buchung finalisiert. Keine Warnungen offen. Explizite Workflow-Regel existiert. |
| Bedingungen PROPOSE_ONLY | Standardfall. |
| Bedingungen REQUIRE_USER_APPROVAL | Offene Punkte existieren. Zugehörige Buchung nicht finalisiert. Warnungen offen. |
| Risiken | Frühzeitiges Erledigt-Markieren kann offene Aufgaben verdecken. |
| Begründung | Reversibel, aber mit Risiko für übersehene offene Punkte. |

### 4.10. Wiedervorlage anlegen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Frist aus Beleg oder Konfiguration ableitbar. Wiedervorlagetyp definiert. |
| Bedingungen PROPOSE_ONLY | Frist nicht eindeutig ableitbar. Mehrere mögliche Wiedervorlagedaten. |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reversibel und informativ) |
| Risiken | Falsche Frist führt zu verpasster Reaktion. |
| Begründung | Reversibel. Informative Aktion. Nutzer wird durch die Wiedervorlage selbst auf das Thema aufmerksam gemacht. |

### 4.11. Reminder senden

| Feld | Wert |
|---|---|
| Standardmodus | PROPOSE_ONLY |
| Bedingungen AUTO | Wiedervorlage-Frist erreicht. Konfigurierte Reminder-Regel existiert. Kanal definiert (Telegram, E-Mail). |
| Bedingungen PROPOSE_ONLY | Standardfall. |
| Bedingungen REQUIRE_USER_APPROVAL | Reminder an externe Dritte. Reminder betrifft finanziellen Sachverhalt. |
| Risiken | Ungewollter Reminder stört Nutzer oder externe Empfänger. |
| Begründung | Externer Seiteneffekt. Nicht irreversibel, aber wahrnehmbar. PROPOSE_ONLY als Default. |

### 4.12. Problemfall erzeugen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Problemkriterium erfüllt (Duplikat, Mismatch, fehlende Daten, Konflikt). |
| Bedingungen PROPOSE_ONLY | – (nicht vorgesehen) |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da rein dokumentierende Aktion) |
| Risiken | Keine. Problemfall-Log ist informativ und schützend. |
| Begründung | Problemfälle müssen sofort erfasst werden. Verzögerung erhöht Risiko für übersehene Fehler. |

### 4.13. Menschenlesbare Prüfsicht erzeugen

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Immer. Bei jedem Fall, der einen Audit-Trail hat. |
| Bedingungen PROPOSE_ONLY | – (nicht vorgesehen) |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da reine Leseoperation) |
| Risiken | Keine. Rein informative Aktion. |
| Begründung | Prüfsichten sind Pflicht laut GoBD-/Compliance-Policy. Keine Verzögerung zulässig. |

### 4.14. Wiederkehrenden Beleg als Entwurf anlegen

| Feld | Wert |
|---|---|
| Standardmodus | PROPOSE_ONLY |
| Bedingungen AUTO | Wiederkehrendes Muster durch mindestens 3 vorherige identische Belege bestätigt. Alle Pflichtdaten vorhanden. Keine Abweichung zum Vorgänger. Explizite Workflow-Regel existiert. |
| Bedingungen PROPOSE_ONLY | Standardfall. Muster erkannt, aber weniger als 3 Belege oder Abweichung vorhanden. |
| Bedingungen REQUIRE_USER_APPROVAL | Erstmaliges Muster. Betrag weicht signifikant von Vorgänger ab. |
| Risiken | Falsches Muster erzeugt fehlerhafte Entwürfe in Serie. Folgefehler potentiell hoch. |
| Begründung | Serienfehler-Risiko. Muster muss validiert sein, bevor AUTO greift. |

### 4.15. Korrekturfall markieren

| Feld | Wert |
|---|---|
| Standardmodus | AUTO |
| Bedingungen AUTO | Korrekturbedarf durch Agent oder Nutzer identifiziert. |
| Bedingungen PROPOSE_ONLY | – (nicht vorgesehen) |
| Bedingungen REQUIRE_USER_APPROVAL | – (nicht vorgesehen, da rein dokumentierende Aktion) |
| Risiken | Keine. Markierung ist informativ und schützend. |
| Begründung | Korrekturfälle müssen sofort sichtbar sein. Verzögerung erhöht Risiko. |

### 4.16. Dokument löschen

| Feld | Wert |
|---|---|
| Standardmodus | REQUIRE_USER_APPROVAL |
| Bedingungen AUTO | Nicht vorgesehen. Keine AUTO-Löschung von Dokumenten zulässig. |
| Bedingungen PROPOSE_ONLY | – (für irreversible Aktion nicht ausreichend) |
| Bedingungen REQUIRE_USER_APPROVAL | Immer. |
| Risiken | Irreversibler Datenverlust. GoBD-Konformität betroffen. Referenzketten werden unterbrochen. |
| Begründung | Maximales Risiko. Löschung ist irreversibel und kann Aufbewahrungspflichten verletzen. |

---

## 5. Übersichtstabelle

| # | Aktion | Standardmodus | AUTO möglich | Hochstufung bei |
|---|---|---|---|---|
| 4.1 | Dokumenttyp erkennen | AUTO | Ja | Low Confidence |
| 4.2 | Tags setzen | AUTO | Ja | Mehrdeutigkeit |
| 4.3 | Korrespondent zuweisen | AUTO | Ja | Low Confidence, unbekannter Korrespondent |
| 4.4 | OCR-Nachanalyse anstoßen | AUTO | Ja | – |
| 4.5 | Bill/Invoice-Draft anlegen | PROPOSE_ONLY | Bei Workflow-Regel | Fehlende Daten, Duplikat, Konflikt |
| 4.6 | Buchung finalisieren | REQUIRE_USER_APPROVAL | Nur bei expliziter Regel | – (bereits höchste Stufe) |
| 4.7 | Zahlungsvorschlag erstellen | PROPOSE_ONLY | Bei Workflow-Regel | Hoher Betrag, unbekannter Empfänger |
| 4.8 | Zahlung buchen/ausführen | REQUIRE_USER_APPROVAL | Nein | – (bereits höchste Stufe) |
| 4.9 | Dokument als erledigt markieren | PROPOSE_ONLY | Bei Workflow-Regel | Offene Punkte |
| 4.10 | Wiedervorlage anlegen | AUTO | Ja | Unklare Frist |
| 4.11 | Reminder senden | PROPOSE_ONLY | Bei Regel + internem Empfänger | Externer Empfänger |
| 4.12 | Problemfall erzeugen | AUTO | Ja | – |
| 4.13 | Prüfsicht erzeugen | AUTO | Ja | – |
| 4.14 | Wiederkehrenden Beleg als Entwurf | PROPOSE_ONLY | Bei validiertem Muster | Erstmaliges Muster, Abweichung |
| 4.15 | Korrekturfall markieren | AUTO | Ja | – |
| 4.16 | Dokument löschen | REQUIRE_USER_APPROVAL | Nein | – (bereits höchste Stufe) |
