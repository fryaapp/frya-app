---
name: traefik-routing-check
description: Prüfe und kläre Traefik-Hostrouting im Frya-Staging (agent/api/weitere Subdomains), markiere Legacy-Routen eindeutig und sichere die gewünschte Außenwahrheit.
---

# Traefik Routing Check

## Zweck
Routing-Wahrheit herstellen: welcher Host zeigt auf welchen Dienst.

## Wann diese Skill zu verwenden ist
- Bei Host-Konflikten zwischen Agent und Legacy-Backend.
- Bei Not-Found/Fehlrouting trotz laufender Container.
- Bei geplanter Host-Migration ohne Downtime-Risiko.

## Wann diese Skill nicht zu verwenden ist
- Bei internen API-Bugs ohne Routingbezug.
- Bei DNS-Änderungen außerhalb des aktuellen Schritts.

## Arbeitsweise
1. Aktive Router/Services/Labels erfassen.
2. Host-zu-Service-Zuordnung dokumentieren (Ist).
3. Zielzuordnung festlegen (inkl. Legacy-Markierung).
4. Minimale Label-/Compose-Anpassung durchführen.
5. Verifikation über Host-Endpunkte mit Statuscodes.

## Grenzen / Verbote
- Keine Hauruck-Änderung ohne Ist-Aufnahme.
- Keine Unterbrechung funktionierender Agent-Route.
- Kein Verschweigen von Legacy-Pfaden.

## Erwartete Ausgabe
- Ist-Mapping und Ziel-Mapping.
- Betroffene Dateien/Labels.
- Prüfprotokoll pro Host.
- Rollback-Hinweis.