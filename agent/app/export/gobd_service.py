"""GoBD / GDPdU export service — Betriebspruefer-Export.

Generates a ZIP archive containing:
  - index.xml   (GDPdU table descriptions)
  - buchungen.csv
  - belege.csv
  - audit_trail.csv
  - kontakte.csv
  - offene_posten.csv
  - verfahrensdokumentation.txt
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date
from xml.etree.ElementTree import Element, SubElement, tostring

import asyncpg

logger = logging.getLogger(__name__)

# CSV column definitions
_BUCHUNGEN_COLS = [
    'Datum', 'Belegnummer', 'Kontonummer', 'Gegenkonto',
    'Betrag', 'Steuersatz', 'Steuerbetrag', 'Buchungstext', 'Waehrung',
]
_BELEGE_COLS = [
    'Beleg_ID', 'Dokumenttyp', 'Absender', 'Betrag', 'Datum',
    'Paperless_ID', 'Dateiname', 'Confidence', 'Status',
]
_AUDIT_COLS = [
    'Event_ID', 'Zeitstempel', 'Agent', 'Aktion', 'Ergebnis', 'Case_ID',
]
_KONTAKTE_COLS = [
    'ID', 'Name', 'Typ', 'E_Mail',
]
_OFFENE_POSTEN_COLS = [
    'Case_ID', 'Case_Nummer', 'Lieferant', 'Betrag', 'Waehrung', 'Faellig_am', 'Status',
]


class GoBDExportService:
    def __init__(self, database_url: str, akaunting_connector=None) -> None:
        self.database_url = database_url
        self.akaunting = akaunting_connector

    async def generate_export(self, date_from: date, date_to: date) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('buchungen.csv', await self._export_buchungen(date_from, date_to))
            zf.writestr('belege.csv', await self._export_belege(date_from, date_to))
            zf.writestr('audit_trail.csv', await self._export_audit_trail(date_from, date_to))
            zf.writestr('kontakte.csv', await self._export_kontakte())
            zf.writestr('offene_posten.csv', await self._export_offene_posten())
            zf.writestr('index.xml', self._generate_index_xml())
            zf.writestr('verfahrensdokumentation.txt', self._generate_verdoku(date_from, date_to))
        buffer.seek(0)
        return buffer.read()

    # ── Buchungen ─────────────────────────────────────────────────────────────

    async def _export_buchungen(self, date_from: date, date_to: date) -> str:
        rows: list[list[str]] = []
        if self.akaunting is not None:
            try:
                txs = await self.akaunting.search_transactions(
                    date_from=date_from.isoformat(),
                    date_to=date_to.isoformat(),
                )
                for tx in txs:
                    rows.append([
                        tx.get('paid_at') or tx.get('date') or '',
                        tx.get('reference') or tx.get('number') or '',
                        tx.get('account_id') or '',
                        tx.get('category_id') or '',
                        str(tx.get('amount', '')),
                        '',  # Steuersatz
                        '',  # Steuerbetrag
                        (tx.get('description') or '')[:120],
                        tx.get('currency_code') or 'EUR',
                    ])
            except Exception as exc:
                logger.warning('GoBD buchungen export failed: %s', exc)
        return self._to_csv(_BUCHUNGEN_COLS, rows)

    # ── Belege ────────────────────────────────────────────────────────────────

    async def _export_belege(self, date_from: date, date_to: date) -> str:
        rows: list[list[str]] = []
        try:
            conn = await asyncpg.connect(self.database_url)
            try:
                db_rows = await conn.fetch(
                    """
                    SELECT cd.id, cd.document_type, c.vendor_name, c.total_amount,
                           c.created_at, cd.document_source_id, cd.filename,
                           cd.assignment_confidence, c.status
                    FROM case_documents cd
                    JOIN case_cases c ON c.id = cd.case_id
                    WHERE c.created_at >= $1::date AND c.created_at < ($2::date + 1)
                    ORDER BY c.created_at
                    """,
                    date_from, date_to,
                )
                for r in db_rows:
                    rows.append([
                        str(r['id']),
                        r['document_type'] or '',
                        r['vendor_name'] or '',
                        str(r['total_amount'] or ''),
                        str(r['created_at'] or '')[:10],
                        str(r['document_source_id'] or ''),
                        r['filename'] or '',
                        str(r['assignment_confidence'] or ''),
                        r['status'] or '',
                    ])
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('GoBD belege export failed: %s', exc)
        return self._to_csv(_BELEGE_COLS, rows)

    # ── Audit Trail ───────────────────────────────────────────────────────────

    async def _export_audit_trail(self, date_from: date, date_to: date) -> str:
        rows: list[list[str]] = []
        try:
            conn = await asyncpg.connect(self.database_url)
            try:
                db_rows = await conn.fetch(
                    """
                    SELECT event_id, created_at, agent_name, action, result, case_id
                    FROM frya_audit_log
                    WHERE created_at >= $1::date AND created_at < ($2::date + 1)
                    ORDER BY created_at
                    """,
                    date_from, date_to,
                )
                for r in db_rows:
                    rows.append([
                        r['event_id'] or '',
                        str(r['created_at'] or ''),
                        r['agent_name'] or '',
                        r['action'] or '',
                        r['result'] or '',
                        r['case_id'] or '',
                    ])
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('GoBD audit export failed: %s', exc)
        return self._to_csv(_AUDIT_COLS, rows)

    # ── Kontakte ──────────────────────────────────────────────────────────────

    async def _export_kontakte(self) -> str:
        rows: list[list[str]] = []
        if self.akaunting is not None:
            try:
                contacts = await self.akaunting.search_contacts()
                for c in contacts:
                    rows.append([
                        str(c.get('id', '')),
                        c.get('name', ''),
                        c.get('type', ''),
                        c.get('email', ''),
                    ])
            except Exception as exc:
                logger.warning('GoBD kontakte export failed: %s', exc)
        return self._to_csv(_KONTAKTE_COLS, rows)

    # ── Offene Posten ─────────────────────────────────────────────────────────

    async def _export_offene_posten(self) -> str:
        rows: list[list[str]] = []
        try:
            conn = await asyncpg.connect(self.database_url)
            try:
                db_rows = await conn.fetch(
                    """
                    SELECT id, case_number, vendor_name, total_amount, currency, due_date, status
                    FROM case_cases
                    WHERE status IN ('OPEN', 'ANALYZED', 'PROPOSED', 'APPROVED')
                    ORDER BY due_date NULLS LAST
                    """,
                )
                for r in db_rows:
                    rows.append([
                        str(r['id']),
                        r['case_number'] or '',
                        r['vendor_name'] or '',
                        str(r['total_amount'] or ''),
                        r['currency'] or 'EUR',
                        str(r['due_date'] or ''),
                        r['status'] or '',
                    ])
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('GoBD offene_posten export failed: %s', exc)
        return self._to_csv(_OFFENE_POSTEN_COLS, rows)

    # ── Index XML ─────────────────────────────────────────────────────────────

    def _generate_index_xml(self) -> str:
        root = Element('DataSet')
        root.set('xmlns', 'urn:gdpdu:1.0')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        version = SubElement(root, 'Version')
        version.text = '1.0'

        tables = [
            ('buchungen.csv', 'Buchungen', 'Buchungsjournal', _BUCHUNGEN_COLS),
            ('belege.csv', 'Belege', 'Belegverzeichnis', _BELEGE_COLS),
            ('audit_trail.csv', 'Audit_Trail', 'Pruefprotokoll', _AUDIT_COLS),
            ('kontakte.csv', 'Kontakte', 'Kunden und Lieferanten', _KONTAKTE_COLS),
            ('offene_posten.csv', 'Offene_Posten', 'Offene Forderungen und Verbindlichkeiten', _OFFENE_POSTEN_COLS),
        ]

        for filename, name, desc_text, columns in tables:
            media = SubElement(root, 'Media')
            table = SubElement(media, 'Table')
            SubElement(table, 'URL').text = filename
            SubElement(table, 'Name').text = name
            SubElement(table, 'Description').text = desc_text
            for col_name in columns:
                col = SubElement(table, 'VariableColumn')
                SubElement(col, 'Name').text = col_name

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding='unicode')

    # ── Verfahrensdokumentation ───────────────────────────────────────────────

    def _generate_verdoku(self, date_from: date, date_to: date) -> str:
        return (
            'FRYA Verfahrensdokumentation — GoBD-Export\n'
            '==========================================\n\n'
            f'Exportzeitraum: {date_from.isoformat()} bis {date_to.isoformat()}\n\n'
            'Dieses Archiv enthaelt:\n'
            '  - buchungen.csv: Alle Buchungen im Zeitraum (Quelle: Akaunting)\n'
            '  - belege.csv: Alle Belege/Dokumente (Quelle: CaseEngine + Paperless)\n'
            '  - audit_trail.csv: Lueckenloses Pruefprotokoll aller Agenten-Aktionen\n'
            '  - kontakte.csv: Kunden- und Lieferantenstammdaten (Quelle: Akaunting)\n'
            '  - offene_posten.csv: Offene Forderungen und Verbindlichkeiten\n'
            '  - index.xml: GDPdU-Indexdatei (Tabellenbeschreibungen)\n\n'
            'Aufbewahrungsfristen (§147 AO / §14b UStG):\n'
            '  - Buchungen, Belege, Audit-Trail: 10 Jahre\n'
            '  - Kontakte, Offene Posten: 10 Jahre\n\n'
            'System: FRYA v3 — KI-gestuetzte Buchhaltungsassistenz\n'
            'Hinweis: KI-generierte Daten — bitte pruefen.\n'
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_csv(columns: list[str], rows: list[list[str]]) -> str:
        out = io.StringIO()
        writer = csv.writer(out, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([str(v) for v in row])
        return out.getvalue()
