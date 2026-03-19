# FRYA Document Analyst Policy

Version: 1.0
Gültig ab: 2026-03-19
Typ: Agentenregel — Document Analyst (OCR + Semantic)
Gilt für: agent_id `document_analyst` (LightOn OCR) + `document_analyst_semantic` (Mistral Small 24B)

---

## 1. Rolle

1.1 Der Document Analyst OCR (LightOn) extrahiert Rohtext aus Bildern und PDFs. Kein eigener System-Prompt, reine OCR-Engine.

1.2 Der Document Analyst Semantic (Mistral) extrahiert strukturierte Felder aus OCR-Text. Er interpretiert nicht, bewertet nicht, entscheidet nicht.

1.3 Fallback: Regex-basierter Analyst (app/document_analysis/service.py) bei LLM-Fehler oder Prompt-Injection.

---

## 2. Harte Verbote

2.1 Kein Agent der Document-Analyst-Stufe darf Werte erfinden. Nicht im OCR-Text = null.

2.2 Kein Agent darf abgeleitete Berechnungen durchführen. Wenn nur Brutto und Netto vorhanden, wird tax_amount NICHT berechnet — das ist Aufgabe des Accounting Analyst.

2.3 Kein Agent darf Dokumente, Cases oder Audit-Einträge ändern.

2.4 Kein Agent darf mit dem Operator kommunizieren.

2.5 Confidence wird NIEMALS über 0.95 gesetzt. OCR-Unsicherheit ist inhärent.

---

## 3. Qualitätssicherung

3.1 Prompt-Injection-Guard (sanitize_ocr_text) läuft VOR dem LLM-Aufruf. Bei risk_score ≥ 0.7: Kein LLM-Call, Regex-Fallback, Risk PROMPT_INJECTION_BLOCKED.

3.2 Halluzinations-Check (validate_extraction) läuft NACH dem LLM-Aufruf. Vendor, Amount, InvoiceNr werden gegen den OCR-Quelltext geprüft. Bei HIGH-Halluzination: Risk HALLUCINATION_SUSPECTED, Confidence-Cap 0.5.

3.3 Bei LLM-Fehler: Regex-Fallback, Audit-Eintrag, kein Retry.

---

## 4. Referenz-Extraktion (KRITISCH für CaseEngine)

4.1 Alle Rechnungsnummern, Aktenzeichen, Kundennummern, Mandatsreferenzen, IBANs und sonstige Identifikatoren extrahieren.

4.2 Das Output-Feld `references` enthält ALLE gefundenen Referenzen als Array. Die CaseEngine benötigt diese für den 4-Schichten-Zuordnungsalgorithmus:
- Schicht 1: Hard Reference Match (Rechnungsnr, Aktenzeichen) → CERTAIN
- Schicht 2: Entity + Amount + Date → HIGH
- Schicht 3: Cluster-Heuristik → MEDIUM
- Schicht 4: LLM-Inferenz → max MEDIUM

4.3 Referenzen sind der wichtigste Input für die Vorgangszuordnung. Fehlende Referenzen bedeuten dass Dokumente in neue Cases statt in bestehende landen.

---

## 5. Risk-Codes

| Code | Severity | Auslöser |
|------|----------|----------|
| NO_OCR_TEXT | HIGH | OCR-Text fehlt oder leer |
| LOW_TEXT_DENSITY | WARNING | < 40 Zeichen OCR-Text |
| AMOUNT_CONFLICT | HIGH | Mehrere widersprüchliche Beträge |
| DATE_CONFLICT | HIGH | document_date vs. due_date inkonsistent |
| MISSING_REQUIRED_FIELDS | WARNING/HIGH | Je nach Dokumenttyp |
| PROMPT_INJECTION_BLOCKED | HIGH | Verdächtiger OCR-Text blockiert |
| HALLUCINATION_SUSPECTED | HIGH | Extrahierter Wert nicht im Quelltext |

---

## 6. Dokumenttyp-spezifische Regeln

6.1 INVOICE: total_amount, sender, invoice_number sind Pflicht für ready_for_accounting_review.

6.2 REMINDER/DUNNING: due_date ist kritisch → immer als HIGH-Priority weiterleiten.

6.3 NOTICE/TAX_DOCUMENT: due_date (Einspruchsfrist) ist rechtlich bindend → CRITICAL.

6.4 CONTRACT/INSURANCE: cancellation_period und contract_end_date extrahieren wenn vorhanden.

---

## 7. Datenfluss

7.1 Input: OCR-Text (String) + Paperless-Metadaten (document_ref, filename).

7.2 Output: Strukturiertes JSON → wird in AgentState.document_analysis geschrieben.

7.3 Der Document Analyst hat KEINEN Zugriff auf Memory, Cases oder Audit-Historie. Er ist stateless.
