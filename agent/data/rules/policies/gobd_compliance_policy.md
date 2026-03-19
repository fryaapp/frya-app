# FRYA GoBD-/Compliance-Policy

Version: 1.0
Gültig ab: 2026-03-08
Typ: Systemregel – Nachvollziehbarkeit, Vollständigkeit, Prüfspur

Hinweis: Diese Datei ist keine Rechtsberatung. Sie definiert System-Policies für Nachvollziehbarkeit, Vollständigkeit, Freigabekonformität und Prüfspur innerhalb des Frya-Systems.

---

## 1. Zweck

Diese Policy stellt sicher, dass alle dokumenten- und buchhaltungsnahen Vorgänge in Frya nachvollziehbar, vollständig, referenzierbar und prüfbar sind.

## 2. Geltungsbereich

Gilt für: alle Dokumentvorgänge, alle finanziellen Vorgänge, alle automatisierten Aktionen, alle manuellen Eingriffe. Kein Vorgang darf ausgenommen werden.

## 3. Pflicht zur Prüfspur

3.1. Kein Vorgang darf ohne zugehörigen Audit-Eintrag abgeschlossen werden.

3.2. Jeder Audit-Eintrag enthält: Zeitstempel (UTC), Vorgangstyp, betroffenes Objekt (Dokument-ID, Buchungs-ID, Case-ID), handelnder Akteur (Agent-ID, Nutzer-ID, Workflow-ID), Aktion, Ergebnis, Begründung oder Regelreferenz.

3.3. Audit-Einträge dürfen nicht gelöscht, überschrieben oder nachträglich inhaltlich verändert werden.

3.4. Korrekturen an Audit-Einträgen sind nur als neue, referenzierende Einträge zulässig. Der Originaleintrag bleibt erhalten.

3.5. Kein System-Neustart, kein Deployment und kein Migrationsprozess darf Audit-Einträge entfernen.

## 4. Pflicht zur Referenzierbarkeit

4.1. Jeder Vorgang muss auf die auslösende Quelle referenzierbar sein: Dokument-ID (Paperless), Buchungs-ID (Akaunting), Case-ID (PostgreSQL), Workflow-ID (n8n), Nutzeranfrage-ID.

4.2. Kein Vorgang darf ohne mindestens eine Referenz existieren.

4.3. Referenzketten müssen rückverfolgbar sein: Von Buchung zurück zu Originaldokument und Entscheidungskette.

4.4. Keine Referenz darf nachträglich entfernt oder umgebogen werden.

## 5. Regeln für Änderungen und Korrekturen

5.1. Jede Änderung an einem finanziellen Zustand muss als neuer Eintrag dokumentiert werden, mit Verweis auf den vorherigen Zustand.

5.2. Der Originalzustand bleibt immer erhalten. Physisches Löschen ist verboten.

5.3. Korrekturen an Buchungsvorschlägen: Neuer Vorschlag mit Referenz auf den alten. Nicht den alten überschreiben.

5.4. Stornierungen: Stornobuchung als neuer Vorgang, nicht als Löschung.

## 6. Regeln für Auto-Aktionen

6.1. Jede automatische Aktion muss die auslösende Regel und die erfüllten Bedingungen im Audit-Eintrag dokumentieren.

6.2. Automatische Aktionen, die eine definierte Schwelle überschreiten, erfordern eine vorgelagerte Freigabe.

6.3. Kein automatischer Vorgang darf eine irreversible Zustandsänderung vornehmen ohne explizite Workflow-Regel.

## 7. Regeln für Freigaben und Eskalationen

7.1. Jede Freigabe wird mit Zeitstempel, Nutzer-ID, Case-ID und Freigabe-Gegenstand dokumentiert.

7.2. Eskalationen enthalten: Problem, Optionen, Referenzen, auslösende Constraints.

7.3. Keine Eskalation darf ohne Nutzerantwort automatisch geschlossen werden.

## 8. Regeln für Ausnahmefälle

8.1. Jede Ausnahme von der Standard-Policy erfordert eine dokumentierte Begründung und einen Audit-Eintrag.

8.2. Kein Agent darf eine Ausnahme eigenständig definieren.

8.3. Ausnahmen gelten nur für den konkreten Fall, nicht als neue Regel.

## 9. Regeln für menschenlesbare Prüfsichten

9.1. Für jeden Vorgang muss eine menschenlesbare Prüfsicht erzeugbar sein.

9.2. Die Prüfsicht enthält: Vorgangstitel, Status, Timeline aller Ereignisse, zugeordnete Dokumente, Audit-Trail, offene Punkte, Konflikte.

9.3. Die Prüfsicht referenziert alle Quellen. Keine Zusammenfassung ohne Quellennachweis.

## 10. Blocker- und Warnkriterien

### Blocker (Vorgang wird gestoppt)
- Pflichtfeld fehlt und ist nicht ableitbar
- Referenzkette unterbrochen
- Finanzielle Zustandsänderung ohne Freigabe
- Audit-Eintrag nicht schreibbar
- Widerspruch zwischen Dokumentwahrheit und finanzieller Wahrheit

### Warnungen (Vorgang läuft weiter, wird markiert)
- Confidence unter Schwellenwert
- Niedrige OCR-Qualität
- Betrag weicht signifikant von historischen Werten ab
- Steuerrelevante Daten unvollständig
