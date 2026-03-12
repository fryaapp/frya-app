---
name: telegram-v1-operator-channel
description: Schärfe Telegram in Frya als kontrollierten Operator-Kanal V1 mit engem Intent-Scope, Zugriffskontrolle, Auditpflicht und ohne freien Chatbot-Modus.
---

# Telegram V1 Operator Channel

## Zweck
Telegram nutzbar machen, ohne Architektur-, Compliance- oder Freigaberegeln zu brechen.

## Wann diese Skill zu verwenden ist
- Bei Telegram-Webhook-Integration im Frya-Agenten.
- Bei Einführung eines minimalen, operativen Command-Sets.
- Bei Bedarf nach auditierbaren Operator-Antworten.

## Wann diese Skill nicht zu verwenden ist
- Bei Wunsch nach freier Chat-Konversation.
- Bei Features ohne vorhandenen Backend-Pfad.
- Bei irreversiblen Finanzaktionen ohne Approval-Logik.

## Arbeitsweise
1. Bestehenden Webhook-Pfad prüfen: Empfang, Normalisierung, Orchestrator, Reply.
2. V1-Intents eng definieren (z. B. status, open-items, problem-cases, case.show, approval.respond, help).
3. Allowlist für Chat-IDs/User-IDs durchsetzen.
4. Unautorisierte Zugriffe kurz ablehnen und auditieren.
5. Für jeden Intent deterministischen Backend-Pfad verwenden, keine freie LLM-Ausführung erzwingen.
6. Antwortstil knapp, operator-orientiert, ohne Scheinsicherheit.

## Grenzen / Verbote
- Kein freier Chatbot-Modus.
- Keine Policy-Änderung über Telegram.
- Keine direkte irreversible Finanzaktion über Telegram.
- Keine Datenlecks an nicht autorisierte Chats.

## Erwartete Ausgabe
- Aktueller Telegram-Status: Code vorhanden vs. live nachgewiesen.
- Definierter V1-Intent-Scope.
- Auth- und Audit-Regeln.
- Konkrete E2E-Checkliste.