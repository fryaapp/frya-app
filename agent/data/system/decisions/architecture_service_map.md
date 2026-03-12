# Architektur-Entscheidung: Service-Map und Legacy-Abgrenzung

Stand: 2026-03-08

## Zielbild
- Der Frya-Agent ist das einzige Backend.
- Ein separater Backend-Service ist Legacy und nicht Teil der Zielarchitektur.

## Services (Remain)
- agent
- traefik
- n8n
- redis
- paperless
- tika
- gotenberg
- postgres
- akaunting
- mariadb
- uptime-kuma
- keys-ui
- watchtower

## Legacy-only
- separate-backend-service (falls noch vorhanden)

## Optionale Extensions
- paperless-ai
- paperless-gpt

## Kritisch (keine blinden Auto-Updates)
- paperless
- akaunting
- mariadb
- postgres
- agent
- n8n
- traefik

## Watchtower-Leitlinie
Für kritische Services darf Architektur nicht auf unbeaufsichtigte Blind-Updates setzen.
