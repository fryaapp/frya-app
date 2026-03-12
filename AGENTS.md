# FRYA REPO RULES

You must start every response with:

>JA<

If these repo instructions are not active or are contradicted, output:

>NEIN<

and stop.

## Project truth

Frya is not a chatbot. Frya is a digital employee for document-near and accounting-near processes.

## Non-negotiable architecture

- The agent itself is the backend.
- There is no separate new backend in the target architecture.
- n8n remains for deterministic workflows and side effects.
- Akaunting is the source of truth for financial truth.
- Paperless is the source of truth for original documents and OCR/archive context.
- PostgreSQL audit is the source of truth for decisions, approvals, and execution history.
- Open Items are operationally stored in PostgreSQL.
- Problem Cases are operationally stored in PostgreSQL.
- Redis is the queue/job backbone.
- Rule files are external, visible in the backend, and auditable when changed.
- The server-rendered FastAPI UI is the operator surface.
- Agents must never execute irreversible financial actions without approval or explicit deterministic workflow rules.

## Work rules

- Do not reopen already decided architecture questions.
- Work package by package.
- Keep responses compact in the required shorthand format.
- Separate strictly:
  - architecture/planned
  - implemented in code
  - tested locally
  - proven live in staging
- No project replay unless explicitly requested.
- No broad redesign unless explicitly requested.

## Frya operating principles

- Audit, memory, and human-in-the-loop are core layers, not add-ons.
- Underagents must have narrow roles and structured outputs.
- n8n handles deterministic and repetitive process execution.
- The orchestrator handles uncertainty, delegation, conflict handling, and final recommendation/decision logic.
- No silent policy changes.
- No silent side effects.
- No pretending certainty where there is uncertainty.

## Current reporting format

Always use:

PKG: <package name>
STEP: <x/y>
Δ: <only affected progress values old->new>
DONE:
- ...
FILES:
- + <new file>
- ~ <changed file>
TEST:
- ...
LIVE:
- ...
BLK:
- <real blockers or none>
NEXT:
- <exactly one next step>

Optional only if truly necessary:

DETAIL:
- ...
- ...

## Current development priority order

1. First real live underagent: Document Analyst
2. Bank/Transaction flow
3. Email ingestion later

## Document Analyst V1 guardrails

- V1 scope is narrow.
- No accounting finalization.
- No payment execution.
- No approval decision by the agent itself.
- Structured extraction only.
- Fact / uncertainty / risk / recommendation must stay separated.
- If OCR is weak or fields conflict, return low confidence or conflict instead of guessing.

## Deployment and truthfulness

- Do not claim live proof without checking the running staging environment.
- Do not claim deploy success without checking the active container/service.
- Do not claim test success without actual test execution.
- If AGENTS instructions seem absent or lost, output `>NEIN<` and stop.
