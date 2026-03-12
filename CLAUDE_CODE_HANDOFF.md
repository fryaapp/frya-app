# Claude Code Handoff

## Read First

- Repo root: `C:\Users\User\Desktop\Frya App`
- Main app: `C:\Users\User\Desktop\Frya App\agent`
- Repo rules: `C:\Users\User\Desktop\Frya App\AGENTS.md`
- Global Codex rules on this machine: `C:\Users\User\.codex\AGENTS.override.md`

Frya is not a chatbot.
Frya is the backend.
Work package by package.
Do not reopen architecture.
Do not claim local/test/live proof unless actually verified.

## Required Response Style

Always start with:

`>JA<`

Use the compact format:

`PKG: ...`
`STEP: ...`
`?: ...`
`DONE:`
`FILES:`
`TEST:`
`LIVE:`
`BLK:`
`NEXT:`

Keep local / tested / live strictly separated.

## Local Workspace

Important directories:

- `C:\Users\User\Desktop\Frya App\agent\app`
- `C:\Users\User\Desktop\Frya App\agent\data`
- `C:\Users\User\Desktop\Frya App\agent\tests`

Useful local test commands:

```powershell
cd 'C:\Users\User\Desktop\Frya App\agent'
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pytest tests/test_accounting_operator_review.py
.\.venv\Scripts\python -m pytest tests/test_document_analysis_runtime.py tests/test_accounting_analysis.py
```

## Staging Access

Expected staging host:

- `root@api.staging.myfrya.de`

Current live agent:

- container: `frya-agent`
- internal port: `8001`

Reliable live-proof pattern from the server:

1. get container IP
2. call `http://<container_ip>:8001`

Useful checks:

```bash
docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' frya-agent
docker inspect -f '{{.State.Health.Status}}' frya-agent
docker logs --tail 120 frya-agent
```

Important truth:

- Public self-calls from the server host were not the reliable proof path.
- Live proofs were done directly against the running container endpoint.

## Deploy Pattern

Typical deploy flow used here:

```powershell
tar --exclude='agent/.venv' --exclude='agent/.pytest_cache' --exclude='agent/__pycache__' --exclude='agent/tests/__pycache__' -czf 'tmp_pkgX.tgz' agent
scp 'C:\Users\User\Desktop\Frya App\tmp_pkgX.tgz' root@api.staging.myfrya.de:/tmp/tmp_pkgX.tgz
ssh root@api.staging.myfrya.de "cp /tmp/tmp_pkgX.tgz /opt/dms-staging/tmp_pkgX.tgz && cd /opt/dms-staging && tar -xzf tmp_pkgX.tgz && docker compose up -d --build --force-recreate agent"
ssh root@api.staging.myfrya.de "docker inspect -f '{{.State.Health.Status}}' frya-agent"
```

## Auth / Live Probe Pattern

Protected live checks used this pattern:

- session cookie name: `frya_session`
- secret source: `FRYA_AUTH_SESSION_SECRET`
- cookie created inside container with `itsdangerous.TimestampSigner`
- CSRF token stored in session payload and sent via `x-frya-csrf-token`

Temporary probe scripts live in repo root:

- `tmp_pkg*_live_check.py`

## Current Proven State Through Paket 20

Live-proven so far:

- Document Analyst V1
- Accounting Review draft path
- Accounting Analyst V1
- Operator confirm / reject
- Manual accounting handoff
- Manual handoff `COMPLETED`
- Manual handoff `RETURNED`
- First clarification completion
- Outside-agent accounting completion
- Outside-agent accounting return
- External return re-clarification completion

Conservative guarantees still true:

- no Akaunting write
- no payment
- no finalization
- `execution_allowed=false` stays in conservative operator paths

## Important Live Cases

### `doc-1`

Invoice path.
Live-proven chain:

- `ACCOUNTING_ANALYST_READY`
- `ACCOUNTING_OPERATOR_REVIEW_CONFIRMED`
- `ACCOUNTING_MANUAL_HANDOFF_READY`
- `ACCOUNTING_MANUAL_HANDOFF_COMPLETED`
- `EXTERNAL_ACCOUNTING_COMPLETED`

Key live facts:

- accounting candidate: `INVOICE_STANDARD_EXPENSE`
- outside-agent completion documented
- open items completed cleanly
- no external write

### `doc-4`

Reminder-based return path.
Live-proven chain:

- `ACCOUNTING_ANALYST_READY`
- `ACCOUNTING_OPERATOR_REVIEW_CONFIRMED`
- `ACCOUNTING_MANUAL_HANDOFF_READY`
- `ACCOUNTING_MANUAL_HANDOFF_RETURNED`
- `ACCOUNTING_CLARIFICATION_COMPLETED`
- `EXTERNAL_ACCOUNTING_RETURNED`
- `EXTERNAL_RETURN_CLARIFICATION_COMPLETED`

Key live facts:

- re-clarification path is operational
- `Externen Reminder-Ruecklauf klaeren` ended `COMPLETED`
- `execution_allowed=false`
- no external write

## Latest Finished Package

Latest finished package:

- Paket 20

Package 20 truth:

- local focused: `13 passed`
- local side tests: `8 passed`
- local full: `52 passed`
- staging redeployed
- `doc-4` live-proved to `EXTERNAL_RETURN_CLARIFICATION_COMPLETED`

## Files Most Relevant Now

- `C:\Users\User\Desktop\Frya App\agent\app\accounting_analysis\models.py`
- `C:\Users\User\Desktop\Frya App\agent\app\accounting_analysis\review_service.py`
- `C:\Users\User\Desktop\Frya App\agent\app\api\case_views.py`
- `C:\Users\User\Desktop\Frya App\agent\app\ui\router.py`
- `C:\Users\User\Desktop\Frya App\agent\app\ui\templates\case_detail.html`
- `C:\Users\User\Desktop\Frya App\agent\tests\test_accounting_operator_review.py`

## Temporary Live-Proof Files Present

Useful recent probe files:

- `C:\Users\User\Desktop\Frya App\tmp_pkg19_live_check.py`
- `C:\Users\User\Desktop\Frya App\tmp_pkg19_return_check.py`
- `C:\Users\User\Desktop\Frya App\tmp_pkg20_live_check.py`

Recent tarballs:

- `C:\Users\User\Desktop\Frya App\tmp_pkg19_outside_agent.tgz`
- `C:\Users\User\Desktop\Frya App\tmp_pkg20_reclarification.tgz`

## Immediate Next Step

If continuing from the latest proven state, start with:

- Paket 21: read-only Akaunting reconciliation / lookup behind the conservative end states

Boundary for Paket 21:

- read-only only
- no Akaunting write
- no payment
- no finalization
- keep local / tested / live separate

## Suggested First Checks

```powershell
Get-Content 'C:\Users\User\Desktop\Frya App\AGENTS.md'
Get-Content 'C:\Users\User\Desktop\Frya App\CLAUDE_CODE_HANDOFF.md'
cd 'C:\Users\User\Desktop\Frya App\agent'
.\.venv\Scripts\python -m pytest
ssh root@api.staging.myfrya.de "docker inspect -f '{{.State.Health.Status}}' frya-agent"
```

## Do Not Forget

- package-by-package only
- no architecture replay
- no hidden side effects
- no claim without proof
- prefer direct container-IP live proof on staging

