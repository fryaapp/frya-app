"""Memory Curator Service — FRYA Agent 8/8.

Verantwortlichkeiten:
- Kuratiert memory.md (Langzeitgedächtnis, max ~2000 Tokens)
- Berechnet und schreibt dms-state.md aus PostgreSQL-Daten
- Pflegt user.md mit Nutzerpräferenzen
- Schreibt tägliche Daily Logs (memory/YYYY-MM-DD.md, append-only)
- Liefert Context Assembly für LLM-Calls anderer Agenten
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LLM_TIMEOUT = float(os.environ.get('FRYA_LLM_TIMEOUT', '120'))
from typing import Any

from app.memory_curator.schemas import CurationResult, DmsState, MemoryUpdate

logger = logging.getLogger(__name__)

_TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4  # rough estimate: 1 token ≈ 4 chars
_MEMORY_MAX_TOKENS = 2000
_MEMORY_MAX_CHARS = _MEMORY_MAX_TOKENS * _TOKEN_ESTIMATE_CHARS_PER_TOKEN

_AGENT_MD_DEFAULT = """\
# FRYA Agent

FRYA ist ein KI-gestützter Buchhaltungs-Assistent.
Version: MVP. Sprache: Deutsch.
Aufgabe: Dokumente verarbeiten, Buchhaltungsfälle verwalten, Operator unterstützen.
"""

_SOUL_MD_DEFAULT = """\
# FRYA Prinzipien

- Genauigkeit vor Geschwindigkeit
- Transparenz gegenüber dem Operator
- Der Operator hat das letzte Wort
- Keine Daten erfinden — nur echte Fakten aus dem System nennen
- Guardrails bleiben immer aktiv
"""


def _count_tokens(text: str) -> int:
    return max(1, len(text) // _TOKEN_ESTIMATE_CHARS_PER_TOKEN)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryCuratorService:
    """Memory Curator — liest Daily Logs + DB-Daten, kuratiert Langzeitgedächtnis."""

    def __init__(
        self,
        *,
        data_dir: Path,
        llm_config_repository: Any = None,
        case_repository: Any = None,
        audit_service: Any = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._llm_config_repository = llm_config_repository
        self._case_repo = case_repository
        self._audit_svc = audit_service

    # ── File helpers ──────────────────────────────────────────────────────────

    def _memory_dir(self, tenant_id: uuid.UUID) -> Path:
        d = self._data_dir / 'memory' / str(tenant_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _read_file(self, path: Path) -> str:
        if path.exists():
            return path.read_text(encoding='utf-8')
        return ''

    def _write_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def _ensure_static_files(self, mem_dir: Path) -> None:
        """Create default static memory files if they don't exist."""
        agent_path = mem_dir / 'agent.md'
        soul_path = mem_dir / 'soul.md'
        user_path = mem_dir / 'user.md'
        memory_path = mem_dir / 'memory.md'
        state_path = mem_dir / 'dms-state.md'

        if not agent_path.exists():
            self._write_file(agent_path, _AGENT_MD_DEFAULT)
        if not soul_path.exists():
            self._write_file(soul_path, _SOUL_MD_DEFAULT)
        if not user_path.exists():
            self._write_file(user_path, '')
        if not memory_path.exists():
            self._write_file(memory_path, '')
        if not state_path.exists():
            self._write_file(state_path, '')

    # ── Daily Log ─────────────────────────────────────────────────────────────

    async def append_daily_log(self, tenant_id: uuid.UUID, entry: str) -> None:
        """Append an entry to today's daily log (memory/YYYY-MM-DD.md)."""
        mem_dir = self._memory_dir(tenant_id)
        log_path = mem_dir / f'{_today_str()}.md'
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        line = f'[{timestamp}] {entry.strip()}\n'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line)

    # ── DMS State ─────────────────────────────────────────────────────────────

    async def get_dms_state(self, tenant_id: uuid.UUID) -> DmsState:
        """Calculate current DMS state from DB — no LLM needed."""
        total = 0
        open_count = 0
        overdue_count = 0
        last_doc_at: str | None = None
        active_agents: list[str] = []

        if self._case_repo is not None:
            try:
                cases = await self._case_repo.list_active_cases_for_tenant(tenant_id)
                open_count = sum(1 for c in cases if getattr(c, 'status', '') == 'OPEN')
                overdue_count = sum(1 for c in cases if getattr(c, 'status', '') == 'OVERDUE')
                total = len(cases)

                # Find latest document arrival
                latest_dates = []
                for c in cases:
                    cd = getattr(c, 'created_at', None)
                    if cd is not None:
                        latest_dates.append(str(cd)[:19])
                if latest_dates:
                    last_doc_at = max(latest_dates)
            except Exception as exc:
                logger.debug('get_dms_state: case fetch failed: %s', exc)

        if self._llm_config_repository is not None:
            try:
                configs = await self._llm_config_repository.get_all_configs()
                active_agents = [
                    c['agent_id'] for c in configs
                    if c.get('agent_status') == 'active'
                ]
            except Exception as exc:
                logger.debug('get_dms_state: agent config fetch failed: %s', exc)

        health = 'ok' if (open_count + overdue_count) < 50 else 'warn'

        return DmsState(
            total_cases=total,
            open_cases=open_count,
            overdue_cases=overdue_count,
            last_document_at=last_doc_at,
            active_agents=active_agents,
            system_health=health,
            generated_at=_now_iso(),
        )

    # ── Context Assembly ──────────────────────────────────────────────────────

    async def get_context_assembly(
        self,
        tenant_id: uuid.UUID,
        *,
        conversation_memory: Any = None,
        effective_case_ref: str | None = None,
    ) -> str:
        """Build the complete context string for LLM calls of other agents."""
        mem_dir = self._memory_dir(tenant_id)
        self._ensure_static_files(mem_dir)

        today = _today_str()
        # yesterday
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')

        parts: list[str] = []

        agent_md = self._read_file(mem_dir / 'agent.md')
        if agent_md:
            parts.append(f'[AGENT]\n{agent_md.strip()}\n[/AGENT]')

        user_md = self._read_file(mem_dir / 'user.md')
        if user_md.strip():
            parts.append(f'[NUTZER]\n{user_md.strip()}\n[/NUTZER]')

        soul_md = self._read_file(mem_dir / 'soul.md')
        if soul_md:
            parts.append(f'[PRINZIPIEN]\n{soul_md.strip()}\n[/PRINZIPIEN]')

        memory_md = self._read_file(mem_dir / 'memory.md')
        if memory_md.strip():
            parts.append(f'[LANGZEITGEDAECHTNISS]\n{memory_md.strip()}\n[/LANGZEITGEDAECHTNISS]')

        today_log = self._read_file(mem_dir / f'{today}.md')
        if today_log.strip():
            parts.append(f'[HEUTE {today}]\n{today_log.strip()}\n[/HEUTE]')

        yesterday_log = self._read_file(mem_dir / f'{yesterday}.md')
        if yesterday_log.strip():
            parts.append(f'[GESTERN {yesterday}]\n{yesterday_log.strip()}\n[/GESTERN]')

        state_md = self._read_file(mem_dir / 'dms-state.md')
        if state_md.strip():
            parts.append(f'[DMS-STATE]\n{state_md.strip()}\n[/DMS-STATE]')

        # ── Aktuelle Vorgaenge (Top 5 open cases) ────────────────────────────
        if self._case_repo is not None:
            try:
                cases = await self._case_repo.list_active_cases_for_tenant(tenant_id)
                # Also include DRAFT
                try:
                    drafts = await self._case_repo.list_cases_by_status(tenant_id, 'DRAFT')
                    seen = {c.id for c in cases}
                    for d in drafts:
                        if d.id not in seen:
                            cases.append(d)
                except Exception:
                    pass
                if cases:
                    cases.sort(key=lambda c: c.created_at or datetime.min, reverse=True)
                    case_lines = []
                    for c in cases[:5]:
                        case_lines.append(
                            f'- {c.case_number or c.id}: {c.vendor_name or "?"}, '
                            f'{c.total_amount or "?"} {c.currency or "EUR"}, Status: {c.status}'
                        )
                    parts.append('[AKTUELLE VORGAENGE]\n' + '\n'.join(case_lines) + '\n[/AKTUELLE VORGAENGE]')
            except Exception as exc:
                logger.warning('context_assembly: case list failed: %s', exc)

        # ── Aktueller Vorgang (detailed, from conversation memory) ───────────
        _case_ref = effective_case_ref
        if not _case_ref and conversation_memory and getattr(conversation_memory, 'last_case_ref', None):
            _case_ref = conversation_memory.last_case_ref
        if _case_ref and self._case_repo is not None:
            detail = await self._build_current_case_detail(tenant_id, _case_ref)
            if detail:
                parts.append(f'[AKTUELLER VORGANG]\n{detail}\n[/AKTUELLER VORGANG]')

        return '\n\n'.join(parts)

    async def _build_current_case_detail(self, tenant_id: uuid.UUID, case_ref: str) -> str | None:
        """Build detailed case text for the currently referenced case."""
        case = None

        # Try direct UUID
        try:
            case = await self._case_repo.get_case(uuid.UUID(case_ref))
        except (ValueError, AttributeError):
            pass

        # Audit-trail resolution (doc-25 -> UUID)
        if case is None and self._audit_svc is not None:
            try:
                import re
                events = await self._audit_svc.by_case(case_ref, limit=50)
                for ev in (events or []):
                    if getattr(ev, 'action', '') == 'document_assigned_to_case':
                        result_str = getattr(ev, 'result', '') or ''
                        m = re.search(r'case_id=([0-9a-f-]{36})', result_str)
                        if m:
                            case = await self._case_repo.get_case(uuid.UUID(m.group(1)))
                            break
            except Exception as exc:
                logger.warning('_build_current_case_detail audit resolve failed: %s', exc)

        if case is None:
            return None

        meta = case.metadata or {}
        analysis = meta.get('document_analysis', {})
        booking = meta.get('booking_proposal', {})

        lines = []
        lines.append(f'Vorgang: {case.case_number or case.id} ({case.vendor_name or "?"})')
        lines.append(f'Betrag: {case.total_amount} {case.currency or "EUR"}')

        if analysis.get('net_amount'):
            lines.append(f'Netto: {analysis["net_amount"]}, MwSt {analysis.get("tax_rate", "?")}%: {analysis.get("tax_amount", "?")}')
        if analysis.get('document_number'):
            lines.append(f'Rechnungsnr: {analysis["document_number"]}')
        if analysis.get('document_date'):
            lines.append(f'Datum: {analysis["document_date"]}')
        if analysis.get('sender'):
            lines.append(f'Absender: {analysis["sender"]}')
        if analysis.get('iban'):
            lines.append(f'IBAN: {analysis["iban"]}')

        items = analysis.get('line_items', [])
        if items:
            lines.append('Positionen:')
            for item in items[:10]:
                qty = item.get('quantity', '')
                desc = item.get('description', '?')
                price = item.get('total_price', '')
                lines.append(f'  {qty}x {desc} — {price}')

        if booking.get('skr03_soll_name'):
            lines.append(f'Buchung: {booking["skr03_soll_name"]} -> {booking.get("skr03_haben_name", "")}')

        lines.append(f'Status: {case.status}')
        return '\n'.join(lines)

    # ── Daily Curation ────────────────────────────────────────────────────────

    async def curate_daily(self, tenant_id: uuid.UUID) -> CurationResult:
        """Run daily curation: update memory.md, dms-state.md, user.md."""
        result = CurationResult(tenant_id=str(tenant_id))
        mem_dir = self._memory_dir(tenant_id)
        self._ensure_static_files(mem_dir)

        # ── Step 1: Update dms-state.md ───────────────────────────────────────
        try:
            state = await self.get_dms_state(tenant_id)
            state_content = (
                f'# DMS State — {state.generated_at}\n\n'
                f'- Vorgänge gesamt (aktiv): {state.total_cases}\n'
                f'- Offen: {state.open_cases}\n'
                f'- Überfällig: {state.overdue_cases}\n'
                f'- System-Health: {state.system_health}\n'
                f'- Aktive Agenten: {", ".join(state.active_agents) or "–"}\n'
                + (f'- Letztes Dokument: {state.last_document_at}\n' if state.last_document_at else '')
            )
            state_path = mem_dir / 'dms-state.md'
            self._write_file(state_path, state_content)
            result.dms_state_updated = True
            result.changes.append(MemoryUpdate(
                file_path=str(state_path),
                changes_summary='DMS State aus DB berechnet und geschrieben',
            ))
        except Exception as exc:
            logger.warning('curate_daily: dms-state update failed: %s', exc)

        # ── Step 2: Gather today's daily log + recent events for LLM ─────────
        today = _today_str()
        today_log = self._read_file(mem_dir / f'{today}.md')
        old_memory = self._read_file(mem_dir / 'memory.md')
        tokens_before = _count_tokens(old_memory)
        result.tokens_before = tokens_before

        # ── Step 3: LLM curation of memory.md (only if log or old memory) ────
        new_memory = old_memory
        if today_log.strip() or old_memory.strip():
            llm_memory = await self._curate_memory_with_llm(
                old_memory=old_memory,
                today_log=today_log,
                tenant_id=tenant_id,
            )
            if llm_memory and llm_memory.strip() != old_memory.strip():
                new_memory = llm_memory
                memory_path = mem_dir / 'memory.md'
                self._write_file(memory_path, new_memory)
                result.memory_md_updated = True
                result.changes.append(MemoryUpdate(
                    file_path=str(memory_path),
                    changes_summary='Langzeitgedächtnis aktualisiert',
                    tokens_before=tokens_before,
                    tokens_after=_count_tokens(new_memory),
                ))

        result.tokens_after = _count_tokens(new_memory)

        # ── Step 4: Audit event ───────────────────────────────────────────────
        if self._audit_svc is not None:
            try:
                await self._audit_svc.log_event({
                    'event_id': 'mem-' + uuid.uuid4().hex[:12],
                    'action': 'MEMORY_CURATED',
                    'agent_name': 'memory-curator-v1',
                    'result': 'ok',
                    'case_id': 'system-memory',
                    'llm_output': {
                        'tenant_id': str(tenant_id),
                        'memory_updated': result.memory_md_updated,
                        'dms_state_updated': result.dms_state_updated,
                        'tokens_before': result.tokens_before,
                        'tokens_after': result.tokens_after,
                    },
                })
            except Exception as exc:
                logger.debug('curate_daily: audit log failed: %s', exc)

        result.summary = (
            f'Kuration abgeschlossen. memory.md: {"aktualisiert" if result.memory_md_updated else "unverändert"}. '
            f'dms-state.md: {"aktualisiert" if result.dms_state_updated else "unverändert"}. '
            f'Tokens: {result.tokens_before} → {result.tokens_after}.'
        )
        return result

    async def _curate_memory_with_llm(
        self,
        *,
        old_memory: str,
        today_log: str,
        tenant_id: uuid.UUID,
    ) -> str | None:
        """Call LLM to curate memory.md. Returns new content or None on failure."""
        if self._llm_config_repository is None:
            return None

        try:
            llm_config = await self._llm_config_repository.get_config_or_fallback('memory_curator')
            model_str = (llm_config.get('model') or '').strip()
            if not model_str:
                return None

            provider = (llm_config.get('provider') or '').strip()
            if provider == 'ionos':
                full_model = f'openai/{model_str}'
            elif provider and '/' not in model_str:
                full_model = f'{provider}/{model_str}'
            else:
                full_model = model_str

            api_key = self._llm_config_repository.decrypt_key_for_call(llm_config)
            base_url = llm_config.get('base_url') or None

            import litellm

            system_prompt = """\
Du bist der Memory Curator von FRYA.
Deine Aufgabe: Das Langzeitgedächtnis des Systems destillieren und komprimieren.
Dein Output ist ausschließlich der neue Inhalt von memory.md im Markdown-Format.

═══════════════════════════════════════
WAS INS GEDÄCHTNIS GEHÖRT
═══════════════════════════════════════

Behalte ausschließlich dauerhaft relevante Fakten:
- Nutzerpräferenzen ("Buche Telekom immer auf 4920")
- Gelernte Buchungsregeln ("Amazon-Bestellungen → Konto 3300, 19% MwSt")
- Wiederkehrende Muster ("Telekom-Rechnung kommt um den 15., ca. 145-150 EUR")
- Systemkonfigurationen und bekannte Fehlerquellen
- Wichtige Operator-Entscheidungen ("Steuerberater ist [Name]", "Freelancer, keine USt-Pflicht")
- Ergebnisse aus Problemfällen (gelernte Gegenmaßnahmen)
- Persönliche Erinnerungen des Operators ("Kita-Fest am Samstag", "Blumen für Nina")

═══════════════════════════════════════
WAS VERWORFEN WIRD
═══════════════════════════════════════

Folgendes gehört ausschließlich in den Audit-Log, nicht ins Gedächtnis:
- Einmalige Statusabfragen und Grüße
- Duplikate von Information die bereits in memory.md steht
- Technische Fehlermeldungen ohne Lernwert
- Zwischenergebnisse die im Audit-Log dokumentiert sind

═══════════════════════════════════════
MUSTER-ERKENNUNG
═══════════════════════════════════════

Ein Muster gilt erst als bestätigt wenn es mindestens 3 mal aufgetreten ist.
- Operator korrigiert einmal eine Buchung → Einmalfall, bleibt im Tages-Log
- Operator korrigiert 3 mal dieselbe Buchungsart → Muster, wird als Regel ins Gedächtnis aufgenommen

═══════════════════════════════════════
DATENSCHUTZ
═══════════════════════════════════════

Personenbezogene Daten durch Platzhalter ersetzen:
- Vollständige Namen → [PERSON] (außer Firmennamen, die bleiben)
- IBAN → [IBAN]
- Steuernummern → [STEUERNR]
Firmennamen, Kontonummern (SKR03) und Beträge bleiben unverändert.

═══════════════════════════════════════
FORMAT
═══════════════════════════════════════

Maximal 2000 Tokens. Sprache: Deutsch. Nur den reinen Markdown-Inhalt ausgeben.

Struktur:

# Langzeitgedächtnis FRYA

## Nutzerpräferenzen
- ...

## Gelernte Buchungsregeln
- ...

## Wiederkehrende Muster
- ...

## Bekannte Probleme und Lösungen
- ...

## Persönliches
- ...

## Systemwissen
- ...
"""

            context_parts: list[str] = []
            if old_memory.strip():
                context_parts.append(f'[BESTEHENDES GEDÄCHTNIS]\n{old_memory.strip()}\n[/BESTEHENDES GEDÄCHTNIS]')
            if today_log.strip():
                context_parts.append(f'[HEUTIGE EREIGNISSE]\n{today_log.strip()}\n[/HEUTIGE EREIGNISSE]')

            user_content = '\n\n'.join(context_parts) + '\n\nBitte aktualisiere das Langzeitgedächtnis.'

            call_kwargs: dict = {
                'model': full_model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_content},
                ],
                'max_tokens': 2000,
                'timeout': _LLM_TIMEOUT,
            }
            if api_key:
                call_kwargs['api_key'] = api_key
            if base_url:
                call_kwargs['api_base'] = base_url

            resp = await litellm.acompletion(**call_kwargs)
            raw = (resp.choices[0].message.content or '').strip()

            # Enforce token limit
            if len(raw) > _MEMORY_MAX_CHARS:
                raw = raw[:_MEMORY_MAX_CHARS] + '\n\n[gekürzt]'

            return raw

        except Exception as exc:
            logger.warning('_curate_memory_with_llm failed: %s', exc)
            return None


def build_memory_curator_service(
    data_dir: Path,
    llm_config_repository: Any,
    case_repository: Any,
    audit_service: Any,
) -> MemoryCuratorService:
    """Factory for use in API endpoints."""
    return MemoryCuratorService(
        data_dir=data_dir,
        llm_config_repository=llm_config_repository,
        case_repository=case_repository,
        audit_service=audit_service,
    )
