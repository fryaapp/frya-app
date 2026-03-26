# FRYA – Verfahrensdokumentation (GoBD)

> Gemäß GoBD (BMF-Schreiben vom 28.11.2019), §146 AO, §147 AO, §14b UStG.
> Stand: 2026-03-19

---

## 1. Systembeschreibung

**FRYA** ist ein KI-gestütztes Dokumentenmanagement- und Buchhaltungssystem für kleine und mittelgroße Unternehmen. Das System empfängt Eingangsbelege (Rechnungen, Lieferscheine, Kontoauszüge) über Paperless-ngx, analysiert diese automatisiert mittels Large-Language-Models (LLMs), ordnet sie Buchungsvorgängen zu und archiviert alle Aktionen in einem unveränderlichen, kryptografisch gesicherten Audit-Log.

| Eigenschaft | Wert |
|---|---|
| Betreiber | [BITTE AUSFÜLLEN: Unternehmensname, Adresse] |
| Technologie | Python/FastAPI (Backend), PostgreSQL (Datenbank), Paperless-ngx (Dokumentenarchiv), n8n (Workflow-Automation) |
| Hosting | Hetzner Cloud (Deutschland), Rechenzentrum Nürnberg |
| Mandantenfähigkeit | Ja — vollständige Datentrennung per `tenant_id` auf Datenbankebene |

---

## 2. Datenfluss und Verarbeitungsprozess

```
Beleg (E-Mail/Scanner/Upload)
    ↓
Paperless-ngx (OCR, Volltext)
    ↓
n8n Workflow 05 (Webhook)
    ↓
FRYA CaseEngine (Fallzuordnung, Confidence: HIGH/MEDIUM/LOW)
    ↓
AccountingAnalyst (SKR03/SKR04-Buchungsvorschlag)
    ↓
Operator-Freigabe (Vier-Augen-Prinzip)
    ↓
Buchung + Archivierung in frya_audit_log (append-only, Hash-Chain)
```

1. **Dokumenteneingang:** Belege werden per E-Mail, Scanner oder manuellen Upload in Paperless-ngx erfasst. OCR-Erkennung erzeugt maschinenlesbaren Text.
2. **Webhook-Benachrichtigung:** Paperless löst nach erfolgreicher Verarbeitung einen Webhook an n8n aus (Workflow 05: Paperless Post-Consumption).
3. **Dokumentenanalyse:** FRYA-Agent analysiert Dokument mittels LLM — extrahiert Betrag, Datum, Rechnungsnummer, Lieferant und klassifiziert den Belegtyp.
4. **Fallzuordnung (CaseEngine):** Das Dokument wird automatisch einem offenen Buchungsvorgang (`case_cases`) zugeordnet. Confidence-Level: HIGH / MEDIUM / LOW.
5. **Buchungsvorschlag:** AccountingAnalyst-Agent erzeugt SKR03/SKR04-Buchungsvorschlag. Buchung wird **nicht** ohne Operator-Freigabe gebucht.
6. **Operator-Freigabe:** Autorisierter Nutzer prüft und genehmigt oder lehnt den Vorschlag ab (Vier-Augen-Prinzip).
7. **Archivierung:** Alle Aktionen werden im Audit-Log (`frya_audit_log`) mit Zeitstempel, Nutzer, Aktion, Ergebnis und kryptografischer Hash-Kette gespeichert.
8. **Benachrichtigung:** Telegram-Notifikation an zuständigen Operator bei neuen Belegen und Freigabeerfordernis.

---

## 3. Zugriffskontrolle und Autorisierung

- **RBAC:** Zwei Rollen — *operator* (Standardzugriff auf Dokumente, Fälle, Freigaben) und *admin* (Nutzerverwaltung, Mandantenverwaltung, Konfiguration). Alle Endpunkte serverseitig geprüft.
- **Tenant-Isolation:** Jeder API-Aufruf ist an eine `tenant_id` gebunden. Mandantenübergreifende Zugriffe werden auf Datenbankebene verhindert.
- **Authentifizierung:** JWT-Token (HS256) mit kurzem Ablaufzeitraum. Passwörter: PBKDF2-HMAC-SHA256 (390.000 Iterationen).
- **Datenbanknutzer:** Applikationsnutzer `frya` hat auf GoBD-relevanten Tabellen ausschließlich INSERT- und SELECT-Rechte — UPDATE, DELETE und TRUNCATE sind entzogen (Write-Once-Enforcement, Migration `0012_gobd_write_once.sql`).

---

## 4. Unveränderlichkeit und Integrität des Audit-Logs

Das Audit-Log (`frya_audit_log`) ist append-only und kryptografisch gesichert:

- **Hash-Chain:** Jeder Eintrag enthält `record_hash = SHA-256(previous_hash || JSON-Payload)`. Eine Manipulation eines Eintrags bricht die gesamte Kette.
- **Integritätsprüfung:** `GET /inspect/audit/verify-chain` prüft die vollständige Hash-Kette aller Einträge und gibt `{"valid": true, "entries_checked": N}` zurück.
- **Datenbankebene:** `REVOKE UPDATE, DELETE, TRUNCATE ON frya_audit_log FROM frya` — Applikationsnutzer kann keine Einträge überschreiben oder löschen.
- **Vollständigkeit:** Jede Aktion (Dokumenteneingang, Analyse, Freigabe, Ablehnung, Konfigurationsänderung, Mandantenverwaltung) erzeugt einen Audit-Eintrag.

---

## 5. Aufbewahrungsfristen (§147 AO / §14b UStG)

| Objekt / Tabelle | Aufbewahrungsfrist | Rechtsgrundlage |
|---|---|---|
| Buchungsbelege (`case_documents`) | 10 Jahre | §147 Abs. 1 Nr. 4 AO, §14b UStG |
| Buchungsvorgänge (`case_cases`) | 10 Jahre | §147 Abs. 1 Nr. 1 AO |
| Audit-Protokolle (`frya_audit_log`) | 10 Jahre | §147 Abs. 1 Nr. 1 AO |
| Abrechnungssonderfälle (`frya_problem_cases`) | 10 Jahre | §147 Abs. 1 Nr. 1 AO |
| Nutzerdaten, Konfiguration | 30 Tage (Soft-Delete) | DSGVO Art. 17 (kein GoBD-Bezug) |

Die Aufbewahrungsfristen beginnen mit Ablauf des Kalenderjahres der Erstellung des Dokuments (§147 Abs. 4 AO).

---

## 6. Löschkonzept

### GoBD-geschützte Daten
Buchungsbelege, Buchungsvorgänge und Audit-Logs können vor Ablauf der 10-jährigen Aufbewahrungsfrist systemseitig **nicht** gelöscht werden. Ein Hard-Delete-Versuch wird mit HTTP 409 (GoBD-Sperre) abgewiesen.

### Mandantenlöschung (DSGVO Art. 17 + GoBD)
1. **Soft-Delete:** Mandant wird auf Status `pending_deletion` gesetzt; alle Nutzer deaktiviert. Benachrichtigungs-E-Mail an Mandantenadministrator.
2. **Hard-Delete nach 30 Tagen:** Nutzerdaten und Konfigurationsdaten werden gelöscht.
3. **GoBD-Sperre:** Buchungsdaten bleiben für die Restlaufzeit der 10-jährigen Aufbewahrungsfrist erhalten — auch nach Mandantenlöschung.

### Nutzerdaten (DSGVO Art. 17)
Nutzerdaten unterliegen dem Standard-Löschkonzept (30-Tage-Soft-Delete, dann Hard-Delete). Keine GoBD-Sperre.

---

## 7. Datensicherung (Backup)

| Parameter | Wert |
|---|---|
| Häufigkeit | Täglich (automatisiert) |
| Verschlüsselung | age (X25519-Schlüssel) vor Upload |
| Speicherort | Hetzner Object Storage (S3), Deutschland |
| Aufbewahrungsdauer | [BITTE AUSFÜLLEN: z.B. 90 Tage] |
| Ziel-RPO | [BITTE AUSFÜLLEN, z.B. 24h] |
| Ziel-RTO | [BITTE AUSFÜLLEN, z.B. 4h] |

Wiederherstellung: `pg_restore` + Entschlüsselung mit gesichertem age-Schlüssel.

---

## 8. Softwareversionen und Änderungsmanagement

Alle Codeänderungen werden in Git versioniert. Jeder Deployment-Vorgang wird im Audit-Log protokolliert. Datenbankmigrationen folgen dem Schema `NNNN_beschreibung.sql` und werden versioniert eingecheckt.

---

## 9. Änderungsprotokoll

| Version | Datum | Änderung | Autor |
|---|---|---|---|
| 1.0 | 2026-03-19 | Erststellung der GoBD-Verfahrensdokumentation | [BITTE AUSFÜLLEN] |
