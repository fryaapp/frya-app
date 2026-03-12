# Approval-Modell: Einführung und Integrationspfad

Stand: 2026-03-08

## Entscheidung
Ein dediziertes Approval-Modell wurde eingeführt (`frya_approvals`).

## Warum
Aus Audit-Ereignissen abgeleitete Freigaben sind für robuste Prozesse nicht ausreichend (Status, Entscheidungshistorie, Idempotenz, offene/pending Freigaben).

## Aktuelle Integration
- Approval-Requests werden im Orchestrator-Gate erzeugt.
- Approval-Entscheidungen sind über API erfassbar.
- Case-View zeigt dedizierte Approvals plus audit-abgeleitete Sicht.

## Nächster Ausbau
- Timeout/Expiry-Strategie (EXPIRED) als deterministischer n8n-Workflow.
- Optionales Multi-Approver-Schema pro Aktionstyp.
- Explizite Bindung Approval -> deterministischer Workflow-Schritt-ID.
