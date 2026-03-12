---
name: docker-compose-hardening
description: Härte den bestehenden Frya-Docker/Compose-Stand minimal-invasiv für Staging-Betrieb (Pfade, ENV-Logik, Healthcheck, Watchtower-Risiko, non-root), ohne Neuarchitektur.
---

# Docker Compose Hardening

## Zweck
Bestehenden Betrieb robuster machen, ohne den Stack neu zu entwerfen.

## Wann diese Skill zu verwenden ist
- Bei fragilen Compose-Annahmen (Pfade, Mounts, Hosts, Healthchecks).
- Bei Container-Startproblemen nach Deploy.
- Bei Sicherheits-/Betriebsfragen zu Watchtower, Secrets, Users.

## Wann diese Skill nicht zu verwenden ist
- Bei vollständiger Infrastrukturmigration.
- Bei Kubernetes-Einführung.
- Bei fachlogischen Anforderungen ohne Containerbezug.

## Arbeitsweise
1. Laufende Realität prüfen: Container, Volumes, effektive ENV, Logs.
2. Single-Source-Regeln festziehen:
   - Healthcheck nur an einer Stelle.
   - Provider-ENV nicht widersprüchlich.
3. Datenpfade prüfen (`/app/data`, rules, memory, verfahrensdoku).
4. Watchtower-Label für kritische Services restriktiv halten.
5. Non-root-Laufzeit und Dateirechte belastbar herstellen.

## Grenzen / Verbote
- Keine Gesamtsystem-Migration.
- Keine stille Secret-Hardcodierung.
- Keine blinden Auto-Update-Annahmen für kritische Services.

## Erwartete Ausgabe
- Konkrete Compose-/Dockerfile-Deltas.
- Klarer Runtime-Pfad für persistente Daten.
- Verifikation + Rollback in kurzen Schritten.