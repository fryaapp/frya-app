"""DATEV Buchungsstapel export service — Steuerberater-Uebergabe.

Generates a ZIP archive containing:
  - EXTF_Buchungsstapel.csv  (DATEV header + booking rows)
  - Belegverzeichnis.csv     (document-number-to-file mapping)
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date

logger = logging.getLogger(__name__)

DATEV_HEADER_FIELDS = [
    'EXTF', '700', '21', 'Buchungsstapel', '',
    '', '',   # Berater-Nr, Mandant-Nr
    '', '',   # WJ-Beginn, Sachkontenlaenge
    '', '',   # Datum von, Datum bis
    '', '',   # Erzeugt am, Erzeugt von
    '', '',   # Importiert, Herkunft
    '', '',   # Exportiert von, Reserviert
]

DATEV_COLUMNS = [
    'Umsatz (Soll/Haben)',
    'Soll/Haben-Kennzeichen',
    'WKZ Umsatz',
    'Kurs',
    'Basisumsatz',
    'WKZ Basisumsatz',
    'Konto',
    'Gegenkonto (ohne BU-Schluessel)',
    'BU-Schluessel',
    'Belegdatum',
    'Belegfeld 1',
    'Belegfeld 2',
    'Skonto',
    'Buchungstext',
]


def _bu_schluessel(tax_rate) -> str:
    """DATEV BU-Schluessel for tax rate."""
    try:
        rate = float(tax_rate or 0)
    except (ValueError, TypeError):
        return ''
    if abs(rate - 19) < 0.5:
        return '3'
    if abs(rate - 7) < 0.5:
        return '2'
    return ''


def _german_amount(amount) -> str:
    """Format amount with comma as decimal separator."""
    try:
        val = abs(float(amount or 0))
    except (ValueError, TypeError):
        return '0,00'
    return f'{val:.2f}'.replace('.', ',')


class DATEVExportService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    async def generate_export(
        self,
        date_from: date,
        date_to: date,
        berater_nr: str = '',
        mandant_nr: str = '',
    ) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            datev_csv = await self._generate_buchungsstapel(
                date_from, date_to, berater_nr, mandant_nr,
            )
            zf.writestr('EXTF_Buchungsstapel.csv', datev_csv)

            belege, belegverzeichnis = await self._collect_belege(date_from, date_to)
            zf.writestr('Belegverzeichnis.csv', belegverzeichnis)

        buffer.seek(0)
        return buffer.read()

    async def _generate_buchungsstapel(
        self, date_from: date, date_to: date,
        berater_nr: str, mandant_nr: str,
    ) -> str:
        out = io.StringIO()
        writer = csv.writer(out, delimiter=';', quoting=csv.QUOTE_ALL)

        # DATEV header row
        header = list(DATEV_HEADER_FIELDS)
        header[5] = berater_nr
        header[6] = mandant_nr
        header[7] = date_from.strftime('%Y%m%d')
        header[8] = '4'  # SKR03 = 4-stellig
        header[9] = date_from.strftime('%Y%m%d')
        header[10] = date_to.strftime('%Y%m%d')
        writer.writerow(header)

        # Column headers
        writer.writerow(DATEV_COLUMNS)

        # Booking rows from FRYA accounting
        transactions = await self._get_transactions(date_from, date_to)
        for tx in transactions:
            amount = float(tx.get('amount', 0) or 0)
            raw_date = tx.get('paid_at') or tx.get('date') or ''
            belegdatum = ''
            if raw_date and len(raw_date) >= 10:
                # YYYY-MM-DD → DDMM
                parts = raw_date[:10].split('-')
                if len(parts) == 3:
                    belegdatum = parts[2] + parts[1]

            row = [
                _german_amount(amount),
                'S' if amount >= 0 else 'H',
                'EUR',
                '',  # Kurs
                '',  # Basisumsatz
                '',  # WKZ Basisumsatz
                str(tx.get('account_id') or ''),
                str(tx.get('category_id') or ''),
                _bu_schluessel(tx.get('tax_rate')),
                belegdatum,
                tx.get('reference') or tx.get('number') or '',
                '',  # Belegfeld 2
                '',  # Skonto
                (tx.get('description') or '')[:60],
            ]
            writer.writerow(row)

        return out.getvalue()

    async def _get_transactions(self, date_from: date, date_to: date) -> list[dict]:
        if self.database_url is None:
            return []
        try:
            import asyncpg
            conn = await asyncpg.connect(self.database_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT booking_date, document_number, account_soll, account_haben,
                           gross_amount, tax_rate, description
                    FROM accounting_bookings
                    WHERE booking_date >= $1::date AND booking_date <= $2::date
                    ORDER BY booking_number
                    """,
                    date_from, date_to,
                )
                return [
                    {
                        'paid_at': str(r['booking_date'] or ''),
                        'reference': r['document_number'] or '',
                        'account_id': r['account_soll'] or '',
                        'category_id': r['account_haben'] or '',
                        'amount': float(r['gross_amount'] or 0),
                        'tax_rate': float(r['tax_rate']) if r['tax_rate'] else None,
                        'description': r['description'] or '',
                        'currency_code': 'EUR',
                    }
                    for r in rows
                ]
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning('DATEV transaction fetch failed: %s', exc)
            return []

    async def _collect_belege(self, date_from: date, date_to: date) -> tuple[list[dict], str]:
        """Collect document references and generate Belegverzeichnis CSV."""
        belege: list[dict] = []

        if self.database_url is not None:
            try:
                import asyncpg
                conn = await asyncpg.connect(self.database_url)
                try:
                    rows = await conn.fetch(
                        """
                        SELECT b.document_number, c.name AS vendor_name,
                               b.gross_amount, b.booking_date
                        FROM accounting_bookings b
                        LEFT JOIN accounting_contacts c ON c.id = b.contact_id
                        WHERE b.booking_date >= $1::date AND b.booking_date <= $2::date
                          AND b.booking_type = 'EXPENSE'
                        ORDER BY b.booking_number
                        """,
                        date_from, date_to,
                    )
                    for r in rows:
                        belege.append({
                            'document_number': r['document_number'] or '',
                            'vendor': r['vendor_name'] or '',
                            'amount': str(r['gross_amount'] or ''),
                            'date': str(r['booking_date'] or ''),
                        })
                finally:
                    await conn.close()
            except Exception as exc:
                logger.warning('DATEV belege fetch failed: %s', exc)

        out = io.StringIO()
        writer = csv.writer(out, delimiter=';')
        writer.writerow(['Belegnummer', 'Dateiname', 'Lieferant', 'Betrag', 'Datum'])
        for b in belege:
            doc_nr = b.get('document_number', '')
            vendor = b.get('vendor', '')
            writer.writerow([
                doc_nr,
                f'Belege/{doc_nr}_{vendor}.pdf',
                vendor,
                b.get('amount', ''),
                b.get('date', ''),
            ])

        return belege, out.getvalue()
