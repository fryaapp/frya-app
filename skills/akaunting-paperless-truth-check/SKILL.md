---
name: akaunting-paperless-truth-check
description: Prüfe in Frya strikt die Trennung der Wahrheiten: Akaunting als finanzielle Wahrheit, Paperless als Dokumentwahrheit, und blockiere Vermischung in Entscheidungen, Audits und Flows.
---

# Akaunting Paperless Truth Check

## Zweck
Verhindern, dass Dokument- und Finanzwahrheit logisch vermischt werden.

## Wann diese Skill zu verwenden ist
- Bei Connector-/Orchestrator-Änderungen.
- Bei Case-Synthese mit Beleg- und Finanzreferenzen.
- Bei Konflikten zwischen Dokumentdaten und Buchhaltungsdaten.

## Wann diese Skill nicht zu verwenden ist
- Bei isolierten UI-Themen ohne Datenmodellbezug.
- Bei Infrastrukturthemen ohne fachliche Wahrheitsebene.

## Arbeitsweise
1. Datenquellen je Entscheidungspfad identifizieren.
2. Prüfen, ob finanzielle Entscheidungen nur auf Akaunting-Truth basieren.
3. Prüfen, ob Dokumentreferenzen/OCR nur Paperless-Truth bleiben.
4. Konfliktfälle explizit markieren und blockieren/escalieren.
5. Audit-/Case-Views auf klare Referenzierung prüfen.

## Grenzen / Verbote
- Kein "Best-of-both"-Mischen ohne Regelpfad.
- Keine finale Finanzmutation aus reiner Dokumentheuristik.
- Keine Konfliktglättung ohne sichtbaren Problemfall/Open-Item.

## Erwartete Ausgabe
- Befundliste pro Pfad: konform/nicht konform.
- Konkrete Konfliktfälle und Blockregeln.
- Minimaler Korrekturplan mit Nachweisfeldern im Audit.