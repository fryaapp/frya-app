# Runbook: Rule-Loading in Staging stabil halten

## Zweck
Dieses Runbook verhindert den bekannten Fehlerfall `Required loaded: False` durch leeres `/app/data/rules` bei frischem Agent-Volume.

## Root Cause (historisch)
- Agent nutzt persistentes Volume auf `/app/data`.
- Ein frisches/leereres Volume ueberdeckt Inhalte aus dem Image.
- Ohne Bootstrap fehlen `rule_registry.yaml` und Policy-Dateien zur Laufzeit.

## Dauerhafte Loesung
- Image enthaelt Repo-Defaults unter `/opt/frya-default-data`.
- Startlogik kopiert fehlende Pflichtdateien idempotent in `/app/data`.
- RuleLoader liest weiter aus `FRYA_RULES_DIR` (Standard: `/app/data/rules`).

## Verifikation (live)
1. `docker exec frya-agent ls -la /app/data/rules`
2. `docker exec frya-agent test -f /app/data/rules/rule_registry.yaml && echo RULE_REGISTRY_OK`
3. `curl -ks https://agent.staging.myfrya.de/inspect/rules/load-status/json`
4. `curl -ks https://agent.staging.myfrya.de/ui/system`

Erwartung:
- `loaded` ist gefuellt
- `failed` ist leer
- `Required loaded: True`
- `Missing roles: []`

## Deploy-Hinweis
Nach Dockerfile-Aenderungen immer:
1. `docker compose build agent`
2. `docker compose up -d agent`

## Recovery (falls erneut rot)
1. Mounts pruefen: `docker inspect frya-agent --format '{{json .Mounts}}'`
2. Defaults pruefen: `docker exec frya-agent ls -la /opt/frya-default-data/rules`
3. Runtime pruefen: `docker exec frya-agent ls -la /app/data/rules`
4. Wenn Defaults vorhanden, Runtime leer und Container alt: Agent neu bauen/recreate.

Nur wenn Zeitdruck besteht und Bootstrap/Deploy blockiert ist: einmalig manuelles Kopieren ins Volume als Notfallmassnahme.
