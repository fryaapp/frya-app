---
name: policy-change-with-audit
description: Ändere Frya-Regeldateien ausschließlich mit nachvollziehbarer Versionierung und Auditspur (alt/neu, Benutzer, Zeit, Begründung), ohne stille Regelmutation.
---

# Policy Change With Audit

## Zweck
Regeländerungen kontrolliert, nachvollziehbar und GoBD-orientiert durchführen.

## Wann diese Skill zu verwenden ist
- Bei Änderungen an Policy-/Rule-Dateien.
- Bei UI/API-gestützten Regelupdates mit Auditpflicht.
- Bei Nachweisanforderung zu "wer hat was warum geändert".

## Wann diese Skill nicht zu verwenden ist
- Bei rein lesenden Rule-Checks.
- Bei Änderungen außerhalb des Regelwerks.

## Arbeitsweise
1. Ausgangsversion laden und festhalten.
2. Gezielte Änderung ohne Fachdrift durchführen.
3. Neue Version extrahieren/prüfen.
4. Audit-Eintrag erzwingen mit:
   - file_name
   - old_version
   - new_version
   - changed_by
   - reason
   - changed_at
5. Ladefähigkeit der geänderten Datei direkt verifizieren.

## Grenzen / Verbote
- Keine autonome Policy-Änderung ohne Begründung/Benutzerbezug.
- Kein Überschreiben ohne Altzustand.
- Keine inhaltliche Neuausrichtung außerhalb des Auftrags.

## Erwartete Ausgabe
- Dateiänderung inkl. alter/neuer Version.
- Audit-ID/Change-ID.
- Lade- und Sichtbarkeitsnachweis im Backend.