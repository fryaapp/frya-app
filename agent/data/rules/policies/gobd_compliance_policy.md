# FRYA GoBD-/Compliance-Policy

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Nachvollziehbarkeit, Vollständigkeit, Prüfspur

Hinweis: Diese Datei ist keine Rechtsberatung. Sie definiert System-Policies für Nachvollziehbarkeit, Vollständigkeit, Freigabekonformität und Prüfspur innerhalb des Frya-Systems.

---

## 1. Zweck

Diese Policy stellt sicher, dass alle dokumenten- und buchhaltungsnahen Vorgänge in Frya nachvollziehbar, vollständig, referenzierbar und prüfbar sind.
Sie definiert die Mindestanforderungen an Audit-Trails, Änderungsdokumentation, Freigabeprozesse und menschenlesbare Prüfsichten.

---

## 2. Geltungsbereich

Diese Regeln gelten für:
- Alle Dokumentvorgänge (Upload, Klassifikation, Zuordnung, Archivierung).
- Alle finanziellen Vorgänge (Kontierungsvorschläge, Buchungen, Korrekturen, Stornierungen).
- Alle automatisierten Aktionen (n8n-Workflows, Agent-Entscheidungen).
- Alle manuellen Eingriffe (Nutzerfreigaben, Korrekturen, Ausnahmen).

Kein Vorgang darf von dieser Policy ausgenommen werden, es sei denn, eine dokumentierte Ausnahmeregel existiert.

---

## 3. Pflicht zur Prüfspur

3.1. Kein Vorgang darf ohne zugehörigen Audit-Eintrag abgeschlossen werden.

3.2. Jeder Audit-Eintrag enthält mindestens:
- Zeitstempel (UTC, sekundengenau)
- Vorgangstyp
- Betroffenes Objekt (Dokument-ID, Buchungs-ID, Case-ID)
- Handelnder Akteur (Agent-ID, Nutzer-ID, Workflow-ID)
- Aktion
- Ergebnis
- Begründung oder Regelreferenz

3.3. Audit-Einträge dürfen nicht gelöscht, überschrieben oder nachträglich inhaltlich verändert werden.

3.4. Korrekturen an Audit-Einträgen sind nur als neue, referenzierende Einträge zulässig. Der Originaleintrag bleibt erhalten.

3.5. Kein System-Neustart, kein Deployment und kein Migrationsprozess darf Audit-Einträge entfernen.

---

## 4. Pflicht zur Referenzierbarkeit

4.1. Jeder Vorgang muss auf die auslösende Quelle referenzierbar sein:
- Dokument-ID (Paperless)
- Buchungs-ID (Akaunting)
- Case-ID (PostgreSQL)
- Workflow-ID (n8n)
- Nutzeranfrage-ID

4.2. Kein Vorgang darf ohne mindestens eine dieser Referenzen existieren.

4.3. Referenzketten müssen rückverfolgbar sein: Von der finalen Buchung zurück zum Originaldokument und zur Entscheidungskette.

4.4. Kein Agent und kein Workflow darf eine Referenz entfernen oder durch eine nicht-rückverfolgbare Referenz ersetzen.

---

## 5. Regeln für Änderungen und Korrekturen

5.1. Keine Änderung an einem finanziellen Zustand darf ohne Audit-Eintrag erfolgen.

5.2. Keine Änderung an einem Archivzustand (Dokumentstatus, Klassifikation, Zuordnung) darf ohne Audit-Eintrag erfolgen.

5.3. Korrekturen überschreiben nicht den Originalzustand. Der Originalzustand bleibt als historischer Eintrag erhalten.

5.4. Jede Korrektur enthält:
- Referenz auf den Originaleintrag
- Zeitstempel der Korrektur
- Begründung
- Handelnder Akteur
- Neuer Zustand

5.5. Keine rückwirkende Korrektur darf stillschweigend erfolgen. Rückwirkende Korrekturen erfordern eine explizite Freigabe und einen gesonderten Audit-Eintrag mit Markierung „rückwirkend".

---

## 6. Regeln für Auto-Aktionen

6.1. Keine automatisierte Aktion darf einen finanziellen Zustand ändern, ohne dass die Trigger-Bedingungen im Audit-Eintrag dokumentiert sind.

6.2. Keine automatisierte Aktion darf einen Archivzustand ändern, ohne dass der Auslöser nachvollziehbar protokolliert ist.

6.3. Automatisierte Aktionen, die eine Schwelle überschreiten (konfigurierbar: Betragshöhe, Häufigkeit, Abweichung von Regel), erfordern eine vorgelagerte Freigabe.

6.4. Kein n8n-Workflow darf eine irreversible Aktion ohne vorherige Validierung durch den Orchestrator ausführen, es sei denn, die Workflow-Definition enthält eine explizite Ausnahmeklausel mit dokumentierter Begründung.

6.5. Jede Auto-Aktion muss im Audit-Log als automatisiert gekennzeichnet sein (Akteur: Workflow-ID, nicht Nutzer-ID).

---

## 7. Regeln für Freigaben und Eskalationen

7.1. Keine Freigabe darf implizit angenommen werden. Fehlende Antwort ist keine Zustimmung.

7.2. Jede Freigabe wird als eigener Audit-Eintrag gespeichert:
- Wer hat freigegeben (Nutzer-ID)
- Was wurde freigegeben (Case-ID, Aktion)
- Zeitstempel
- Kontext, auf dessen Basis die Freigabe erteilt wurde

7.3. Eskalationen werden als offene Punkte gespeichert, bis sie aufgelöst sind.

7.4. Keine Eskalation darf automatisch geschlossen werden.

7.5. Jede Eskalation enthält den Grund, die betroffenen Regeln und die Optionen.

---

## 8. Regeln für Ausnahmefälle

8.1. Ausnahmen von diesen Regeln sind nur mit dokumentierter Begründung zulässig.

8.2. Jede Ausnahme wird als eigener Audit-Eintrag gespeichert:
- Referenz auf die Regel, von der abgewichen wird
- Begründung
- Freigebender Akteur
- Zeitstempel
- Geltungsdauer (einmalig oder befristet)

8.3. Keine dauerhafte Ausnahme darf ohne eine Anpassung der Policy-Datei bestehen. Dauerhafte Ausnahmen müssen in eine Regeländerung überführt werden.

8.4. Kein Agent darf eine Ausnahme selbst definieren.

---

## 9. Regeln für menschenlesbare Prüfsichten

9.1. Jeder Fall (Case) muss eine menschenlesbare Prüfsicht erzeugen können.

9.2. Die Prüfsicht enthält mindestens:
- Fallübersicht (Case-ID, Status, Erstelldatum, Letzte Änderung)
- Beteiligte Dokumente mit Referenz auf Paperless
- Beteiligte Buchungen mit Referenz auf Akaunting
- Entscheidungskette (welcher Agent hat was entschieden, wann, warum)
- Offene Punkte
- Freigaben und Eskalationen
- Warnungen und Blocker

9.3. Die Prüfsicht darf keine Rohdaten enthalten, die nicht interpretierbar sind. Alle Einträge müssen für einen menschlichen Prüfer verständlich sein.

9.4. Die Prüfsicht muss ohne technisches Spezialwissen lesbar sein.

9.5. Die Prüfsicht darf keine Daten auslassen, die für die Beurteilung des Falls relevant sind.

---

## 10. Blocker- und Warnkriterien

### Blocker (Vorgang wird gestoppt)

10.1. Pflichtfeld fehlt und ist nicht aus dem Kontext ableitbar.

10.2. Referenzkette ist unterbrochen (z. B. Buchung ohne zugehöriges Dokument).

10.3. Finanzieller Zustand soll geändert werden, aber keine Freigabe liegt vor und keine Automatisierungsregel greift.

10.4. Audit-Eintrag kann nicht geschrieben werden (Datenbankfehler, Timeout).

10.5. Widerspruch zwischen Dokumentkontext und Akaunting-Daten, der nicht automatisch auflösbar ist.

### Warnungen (Vorgang läuft, aber wird markiert)

10.6. Confidence eines Kontierungsvorschlags liegt unter dem konfigurierten Schwellenwert.

10.7. OCR-Qualität ist als niedrig eingestuft.

10.8. Betrag weicht signifikant von historischen Werten für denselben Kreditor ab.

10.9. Steuerrelevante Daten sind unvollständig, aber nicht blockierend.

10.10. Fall enthält offene Punkte aus vorherigen Vorgängen.
