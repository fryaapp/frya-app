---
name: rule-loader-proof
description: Beweise für Frya belastbar, ob Regeldateien (inkl. orchestrator_policy.md) im Runtime-Pfad tatsächlich geladen werden, statt nur formal registriert zu sein.
---

# Rule Loader Proof

## Zweck
Nachweis liefern, dass Registry, Dateien und Runtime-Loader real wirken.

## Wann diese Skill zu verwenden ist
- Bei Aussagen wie "Policy ist live".
- Bei fehlenden Regeln in UI/Systemstatus.
- Nach Deploys mit möglichen Volume-/Pfadproblemen.

## Wann diese Skill nicht zu verwenden ist
- Bei rein inhaltlichen Policy-Textänderungen ohne Laufzeitbezug.
- Bei Offline-Dokumentation ohne Runtime-Prüfung.

## Arbeitsweise
1. Registry-Datei und Rollen-Mapping prüfen.
2. Effektiven Runtime-Pfad prüfen (Container-Dateisystem, ENV, Mounts).
3. Loader-Endpunkte prüfen:
   - `/inspect/rules/load-status/json`
   - `/ui/system`
4. Startup-/Audit-Spuren prüfen (z. B. `POLICY_LOAD_STATUS`).
5. Ergebnis als "geladen", "unklar" oder "nicht nachgewiesen" klassifizieren.

## Grenzen / Verbote
- Kein "grün" ohne überprüfbaren Laufzeitbeleg.
- Keine Annahme, dass Registry-Eintrag automatisch Runtime-Load bedeutet.
- Keine Verschleierung leerer oder fehlerhafter Load-Status.

## Erwartete Ausgabe
- Geladene vs. fehlende Rule-Dateien.
- Pfad-/Mount-Ursache bei Fehllast.
- Minimaler Fixplan (Datei + Maßnahme + Verifikation).