---
name: operator-ui-smoke-check
description: Führe einen schnellen, belastbaren Smoke-Check der servergerenderten Frya-Operator-UI durch (Dashboard, Cases, Open Items, Problem Cases, Rules, System), inklusive Leer-/Fehlerzustände.
---

# Operator UI Smoke Check

## Zweck
Sichtbarkeit schaffen, ob die Operator-UI operativ nutzbar ist.

## Wann diese Skill zu verwenden ist
- Nach Deploys des Agent-Backends.
- Bei gemeldeten Not Found/500-Problemen.
- Vor Übergabe an Operatoren.

## Wann diese Skill nicht zu verwenden ist
- Bei Pixel-Design-Diskussionen.
- Bei Funktionswünschen ohne bestehende Backend-Daten.

## Arbeitsweise
1. Kernseiten prüfen:
   - `/ui/dashboard`
   - `/ui/cases`
   - `/ui/open-items`
   - `/ui/problem-cases`
   - `/ui/rules`
   - `/ui/system`
2. API/Inspect-Gegencheck für gleiche Datenbasis durchführen.
3. Leere Zustände und 500er explizit dokumentieren.
4. Reproduzierbare Fehler mit Datei-/Endpoint-Bezug festhalten.

## Grenzen / Verbote
- Keine erfundenen Daten oder Fake-Management-Aktionen.
- Keine Sicherheit behaupten, wenn Auth/ACL fehlt.
- Kein Overengineering für UI-V1.

## Erwartete Ausgabe
- Seite für Seite: HTTP-Status, Kerninhalt, Fehlerbild.
- Priorisierte Fixliste.
- Minimaler Retest-Plan.