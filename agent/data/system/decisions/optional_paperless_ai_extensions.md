# ADR: paperless-ai / paperless-gpt als optionale Erweiterungen

Stand: 2026-03-08

## Entscheidung
paperless-ai und paperless-gpt bleiben optionale Erweiterungen und sind keine Baseline-Abhaengigkeiten.

## Nutzen
- Zusätzliche KI-gestützte Dokument-Metadaten und Klassifikationshilfen.
- Schnellere Vorverarbeitung vor der Agent-Orchestrierung.

## Risiken / Komplexität
- Zusätzliche operative Komplexität (Deploy, Monitoring, Failure-Modes).
- Zusätzliche Abhängigkeiten und mögliche Modell-/Prompt-Drift.
- Gefahr von Verantwortungsverschiebung weg von klaren Source-of-Truth-Grenzen.

## Architekturvorgabe
- Hauptarchitektur bleibt unabhängig lauffähig ohne diese Erweiterungen.
- Keine Kernfunktion (Approval, Audit, Open Items, Problem Cases) darf von diesen Erweiterungen abhängen.
- Falls später eingeführt: klarer Connector-Boundary und eigener Audit-Pfad.
