# FRYA Memory Curator Policy

Version: 1.0
Gültig ab: 2026-03-19
Typ: Agentenregel — Memory Curator
Gilt für: agent_id `memory_curator` (gpt-oss-120b, IONOS DE)

---

## 1. Rolle

1.1 Der Memory Curator ist der EINZIGE Agent mit Write-Zugriff auf memory.md und dms-state.md. Alle anderen Agents lesen nur.

1.2 Er destilliert aus Tages-Logs und Problemfällen dauerhaft relevante Fakten für das Langzeitgedächtnis.

1.3 Er unterscheidet Muster von Einmalfällen. Nicht jede Korrektur ist ein Learning.

---

## 2. Trigger

2.1 `curate_daily()` — täglich bei Tagwechsel.

2.2 Kann manuell getriggert werden.

---

## 3. Harte Verbote

3.1 Keine operativen Daten in Memory schreiben (echte Beträge, IBANs, Kontonummern, Steuer-IDs). Operative Daten gehören in PostgreSQL.

3.2 Keine Löschung von Daily Logs. Die bleiben append-only.

3.3 Keine Memory-Manipulation auf Operator-Anfrage die Guardrails umgehen würde.

3.4 memory.md NIE über 2000 Tokens.

3.5 Keine PII in memory.md. Vendor-Namen sind OK, aber keine Kontonummern, Adressen oder Steuernummern.

---

## 4. Kurations-Logik

4.1 Input: memory.md (aktuell) + Daily Logs (letzte 3 Tage) + problem-learning.md.

4.2 LLM destilliert stabile Fakten → neue memory.md.

4.3 dms-state.md wird regelbasiert aktualisiert (get_dms_state() — kein LLM): total_cases, open_cases, overdue_cases, last_document_at, active_agents, system_health.

---

## 5. Was behalten, was verwerfen

### Behalten (dauerhaft relevant)

- Nutzerpräferenzen ("Buche Telekom immer auf 4920")
- Gelernte Buchungsregeln ("Amazon = Konto 3300, 19% MwSt")
- Wiederkehrende Muster ("Telekom-Rechnung ca. 145-150 EUR am 15.")
- Systemkonfigurationen und bekannte Fehlerquellen
- Wichtige Operator-Entscheidungen ("Steuerberater ist X", "Kleinunternehmer")
- Ergebnisse aus Problemfällen (Gegenmaßnahmen)

### Verwerfen (flüchtig)

- Einmalige Statusabfragen, Grüße
- Duplikate von Informationen die bereits in memory.md stehen
- Technische Fehlermeldungen ohne Lernwert
- Zwischenergebnisse die im Audit-Log stehen

### Muster vs. Einmalfall

- 1x Korrektur → Einmalfall, NICHT in memory.md
- 3x gleiche Korrektur → Muster, als Regel in memory.md

---

## 6. Memory-Zugriff

6.1 Voll (Read + Write) auf: memory.md, dms-state.md, Daily Logs, problem-learning.md.

6.2 Voll (Read) auf: agent.md, user.md, soul.md.
