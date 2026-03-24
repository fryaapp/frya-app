"""DATEV Buchungsstapel export service — Steuerberater-Uebergabe.

Generates a ZIP archive containing:
  - EXTF_Buchungsstapel.csv  (DATEV header + booking rows)
  - Belegverzeichnis.csv     (document-number-to-file mapping)
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
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
        import uuid as _uuid
        self._tenant_id: _uuid.UUID = _uuid.UUID(int=0)  # default; callers should set via generate_export

    async def generate_export(
        self,
        date_from: date,
        date_to: date,
        berater_nr: str = '',
        mandant_nr: str = '',
        tenant_id: 'uuid.UUID | None' = None,
    ) -> bytes:
        import uuid as _uuid
        if tenant_id is not None:
            self._tenant_id = tenant_id
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
        try:
            from app.accounting.repository import AccountingRepository
            repo = AccountingRepository(self.database_url or 'memory://')
            bookings = await repo.list_bookings(
                self._tenant_id, date_from=date_from, date_to=date_to,
            )
            return [
                {
                    'paid_at': str(b.booking_date or ''),
                    'reference': b.document_number or '',
                    'account_id': b.account_soll or '',
                    'category_id': b.account_haben or '',
                    'amount': float(b.gross_amount or 0),
                    'tax_rate': float(b.tax_rate) if b.tax_rate else None,
                    'description': b.description or '',
                    'currency_code': 'EUR',
                }
                for b in bookings
            ]
        except Exception as exc:
            logger.warning('DATEV transaction fetch failed: %s', exc)
            return []

    async def _collect_belege(self, date_from: date, date_to: date) -> tuple[list[dict], str]:
        """Collect document references and generate Belegverzeichnis CSV."""
        belege: list[dict] = []

        try:
            from app.accounting.repository import AccountingRepository
            repo = AccountingRepository(self.database_url or 'memory://')
            bookings = await repo.list_bookings(
                self._tenant_id, date_from=date_from, date_to=date_to,
            )
            contacts = {c.id: c for c in await repo.list_contacts(self._tenant_id)}
            for b in bookings:
                if b.booking_type == 'EXPENSE':
                    vendor_name = ''
                    if b.contact_id and b.contact_id in contacts:
                        vendor_name = contacts[b.contact_id].name
                    belege.append({
                        'document_number': b.document_number or '',
                        'vendor': vendor_name,
                        'amount': str(b.gross_amount or ''),
                        'date': str(b.booking_date or ''),
                    })
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
