---
name: sequential-architecture-check
description: Prüfe Frya-Änderungen strikt sequenziell gegen die bestehende Zielarchitektur (Agent=Backend, n8n deterministisch, Akaunting/Paperless getrennte Truths, Audit/Open-Items/Problem-Cases Pflicht) und liefere eine belastbare Ist-vs-Ziel-Bewertung ohne Neuarchitektur.
---

# Sequential Architecture Check

## Zweck
Architekturkonformität schrittweise prüfen, ohne auf Greenfield-Annahmen zurückzufallen.

## Wann diese Skill zu verwenden ist
- Bei Sprint-Starts mit bestehendem, gewachsenem Stand.
- Bei Infrastruktur-/Service-Änderungen mit Legacy-Risiko.
- Bei Aufforderung, Ist-Zustand gegen Zielzustand strukturiert zu validieren.

## Wann diese Skill nicht zu verwenden ist
- Bei reinem Bugfix ohne Architekturbezug.
- Bei reinen UI-Textänderungen.
- Wenn der Nutzer ausdrücklich nur eine einzelne Dateiänderung will.

## Arbeitsweise
1. Aktuellen Stand aus Code, Config, Compose und laufenden Endpunkten erfassen.
2. Harte Zielprinzipien prüfen:
   - Agent ist Backend.
   - n8n bleibt deterministische Workflow-Schicht.
   - Akaunting bleibt finanzielle Wahrheit.
   - Paperless bleibt Dokumentwahrheit.
   - Audit/Open Items/Problem Cases sind operativ und persistent.
3. Legacy-Annahmen markieren, nicht still akzeptieren.
4. Abweichungen priorisieren: blockierend, riskant, kosmetisch.
5. Nur minimale, reversible Korrekturen vorschlagen.

## Grenzen / Verbote
- Keine Neuarchitektur vorschlagen.
- Keine stillen Breaking Changes.
- Keine Behauptung "live ok" ohne nachweisbare Prüfung.
- Keine Vermischung von Dokument- und Finanzwahrheit.

## Erwartete Ausgabe
- Kurze Ist-vs-Ziel-Tabelle.
- Liste der Legacy-Reste.
- Konkrete Minimalmaßnahmen mit Dateibezug.
- Verifikationsschritte inkl. Rollback-Hinweis.