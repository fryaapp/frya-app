"""Tests for GoBD + DATEV export services."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import pytest


# ── GoBD Export ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gobd_export_creates_zip():
    from app.export.gobd_service import GoBDExportService

    svc = GoBDExportService('memory://')
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))
    assert len(data) > 0

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert 'index.xml' in names
        assert 'buchungen.csv' in names
        assert 'belege.csv' in names
        assert 'audit_trail.csv' in names
        assert 'kontakte.csv' in names
        assert 'offene_posten.csv' in names
        assert 'verfahrensdokumentation.txt' in names


@pytest.mark.asyncio
async def test_gobd_index_xml_valid():
    from app.export.gobd_service import GoBDExportService

    svc = GoBDExportService('memory://')
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml_content = zf.read('index.xml').decode('utf-8')
        assert '<?xml version="1.0"' in xml_content
        assert 'urn:gdpdu:1.0' in xml_content
        assert '<Name>Buchungen</Name>' in xml_content


@pytest.mark.asyncio
async def test_gobd_buchungen_csv_has_headers():
    from app.export.gobd_service import GoBDExportService

    svc = GoBDExportService('memory://')
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_content = zf.read('buchungen.csv').decode('utf-8')
        reader = csv.reader(io.StringIO(csv_content), delimiter=';')
        headers = next(reader)
        assert 'Datum' in headers
        assert 'Belegnummer' in headers
        assert 'Betrag' in headers


@pytest.mark.asyncio
async def test_gobd_verdoku_contains_zeitraum():
    from app.export.gobd_service import GoBDExportService

    svc = GoBDExportService('memory://')
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        txt = zf.read('verfahrensdokumentation.txt').decode('utf-8')
        assert '2026-01-01' in txt
        assert '2026-03-22' in txt
        assert '10 Jahre' in txt


# ── DATEV Export ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_datev_export_creates_zip():
    from app.export.datev_service import DATEVExportService

    svc = DATEVExportService()
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))
    assert len(data) > 0

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert 'EXTF_Buchungsstapel.csv' in names
        assert 'Belegverzeichnis.csv' in names


@pytest.mark.asyncio
async def test_datev_csv_header_format():
    from app.export.datev_service import DATEVExportService

    svc = DATEVExportService()
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_content = zf.read('EXTF_Buchungsstapel.csv').decode('utf-8')
        reader = csv.reader(io.StringIO(csv_content), delimiter=';', quotechar='"')
        header = next(reader)
        assert header[0] == 'EXTF'
        assert header[1] == '700'
        assert header[2] == '21'


@pytest.mark.asyncio
async def test_datev_csv_columns():
    from app.export.datev_service import DATEVExportService

    svc = DATEVExportService()
    data = await svc.generate_export(date(2026, 1, 1), date(2026, 3, 22))

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_content = zf.read('EXTF_Buchungsstapel.csv').decode('utf-8')
        reader = csv.reader(io.StringIO(csv_content), delimiter=';', quotechar='"')
        next(reader)  # skip header
        columns = next(reader)
        assert 'Umsatz (Soll/Haben)' in columns
        assert 'Soll/Haben-Kennzeichen' in columns
        assert 'Konto' in columns
        assert 'Belegdatum' in columns


@pytest.mark.asyncio
async def test_datev_berater_mandant_nr():
    from app.export.datev_service import DATEVExportService

    svc = DATEVExportService()
    data = await svc.generate_export(
        date(2026, 1, 1), date(2026, 3, 22),
        berater_nr='12345', mandant_nr='67890',
    )

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_content = zf.read('EXTF_Buchungsstapel.csv').decode('utf-8')
        reader = csv.reader(io.StringIO(csv_content), delimiter=';', quotechar='"')
        header = next(reader)
        assert '12345' in header
        assert '67890' in header


def test_datev_bu_schluessel():
    from app.export.datev_service import _bu_schluessel
    assert _bu_schluessel(19) == '3'
    assert _bu_schluessel(7) == '2'
    assert _bu_schluessel(0) == ''
    assert _bu_schluessel(None) == ''


def test_datev_amount_german_format():
    from app.export.datev_service import _german_amount
    assert _german_amount(8.54) == '8,54'
    assert _german_amount(1234.00) == '1234,00'
    assert _german_amount(-19.99) == '19,99'
    assert _german_amount(0) == '0,00'


# ── Agent Translations ────────────────────────────────────────────────────────

def test_agent_translations():
    from app.utils.translations import t_agent
    assert 'Herz' in t_agent('orchestrator')
    assert 'Mund' in t_agent('communicator')
    assert 'Auge' in t_agent('document_analyst')
    assert 'Stirn' in t_agent('document_analyst_semantic')
    assert 'Hand' in t_agent('accounting_analyst')
    assert 'Ohr' in t_agent('deadline_analyst')
    assert 'Nase' in t_agent('risk_consistency')
    assert 'Hirn' in t_agent('memory_curator')


def test_agent_icons():
    from app.utils.translations import t_agent_icon
    icon = t_agent_icon('orchestrator')
    assert icon  # not empty
    icon2 = t_agent_icon('communicator')
    assert icon2
