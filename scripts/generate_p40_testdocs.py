#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P40 TestDocs Generator - Realistische Buchhaltungsbelege
Generiert 10 deutsche Geschaeftsdokumente fuer Testzwecke
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Windows UTF-8 Encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.pdfgen import canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    try:
        from fpdf import FPDF
        HAS_FPDF2 = True
    except ImportError:
        HAS_FPDF2 = False

# Sicherstelle dass test_pdfs/p40 existiert
output_dir = Path(__file__).parent.parent / "test_pdfs" / "p40"
output_dir.mkdir(parents=True, exist_ok=True)

def create_document_reportlab(filename, title, create_content_func):
    """Erstelle PDF mit reportlab"""
    filepath = output_dir / filename

    doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                           rightMargin=1*cm, leftMargin=1*cm,
                           topMargin=1*cm, bottomMargin=1*cm)

    story = []
    create_content_func(story)

    doc.build(story)
    return str(filepath)

def create_document_fpdf2(filename, title, create_content_func):
    """Erstelle PDF mit fpdf2"""
    filepath = output_dir / filename

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)

    create_content_func(pdf)

    pdf.output(str(filepath))
    return str(filepath)

# ============================================================================
# PDF CREATORS (mit reportlab)
# ============================================================================

def create_telekom_mobilfunk(story):
    """1. Deutsche Telekom - Mobilfunk Business"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Deutsche Telekom AG", styles['Title']))
    story.append(Paragraph("Geschäftskundenabrechnung", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Abrechnungsdetails', ''],
        ['Rechnungsnummer:', 'RG-DT-2026-041234'],
        ['Kundennummer:', '9876543210'],
        ['Rechnungsdatum:', '05.04.2026'],
        ['Leistungszeitraum:', '01.04.2026 - 30.04.2026'],
        ['', ''],
    ]

    data.extend([
        ['Leistung', 'Betrag'],
        ['Mobilfunk Business Tarif M', '49,95 EUR'],
        ['Hardware-Versicherung', '5,00 EUR'],
        ['', ''],
        ['Gesamtbetrag (brutto)', '58,23 EUR'],
        ['davon MwSt. (19%)', '8,28 EUR'],
    ])

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#EEEEEE')),
        ('FONTNAME', (0, -2), (-1, -2), 'Helvetica-Bold'),
    ]))
    story.append(table)

def create_axa_kfz(story):
    """2. AXA Kfz-Versicherung"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("AXA Versicherung", styles['Title']))
    story.append(Paragraph("Kfz-Versicherungspolice", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Versicherungsdetails', ''],
        ['Versicherungsnummer:', 'AXA-KFZ-3847562'],
        ['Versicherungsnehmer:', 'Max Mustermann'],
        ['Fahrzeug:', 'BMW 320d | KFZ-Kennzeichen: HD-MM-123'],
        ['Gültig von:', '01.01.2026'],
        ['Gültig bis:', '31.12.2026'],
        ['', ''],
        ['Jahresbeitrag (brutto)', '892,40 EUR'],
        ['davon MwSt. (19%)', '141,65 EUR'],
        ['Leistungsart', 'Vollkasko mit Selbstbeteiligung 300 EUR'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0066CC')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)

def create_stadtwerke_gas(story):
    """3. Stadtwerke Baden-Baden - Gas Q1"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Stadtwerke Baden-Baden", styles['Title']))
    story.append(Paragraph("Gasabrechnung Q1 2026", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Abrechnung', ''],
        ['Kundennummer:', 'SW-BB-987654'],
        ['Zählernummer:', 'G-12-345-6789'],
        ['Abrechnungszeitraum:', '01.01.2026 - 31.03.2026'],
        ['', ''],
        ['Gasverbrauch', '245 kWh'],
        ['Arbeitspreis (kWh)', '0,0895 EUR/kWh = 21,93 EUR'],
        ['Grundgebühr', '15,75 EUR'],
        ['Konzessionsabgabe', '2,50 EUR'],
        ['', ''],
        ['Summe netto', '196,68 EUR'],
        ['MwSt. 19%', '37,37 EUR'],
        ['Fällig', '234,05 EUR'],
        ['Zahlbar bis', '30.04.2026'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF6600')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, -3), (-1, -3), colors.HexColor('#FFEEEE')),
        ('FONTNAME', (0, -3), (-1, -3), 'Helvetica-Bold'),
    ]))
    story.append(table)

def create_amazon_office(story):
    """4. Amazon EU SARL - Büromaterial"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Amazon EU SARL", styles['Title']))
    story.append(Paragraph("Bestellbestätigung", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Bestellinformation', ''],
        ['Bestellnummer:', 'AMZ-2026-045234'],
        ['Bestelldatum:', '02.04.2026'],
        ['Versanddatum:', '03.04.2026'],
        ['', ''],
        ['Artikel', 'Menge', 'Preis'],
        ['Kopierpapier 500er A4 80g/m²', '5', '4,99 EUR'],
        ['Kugelschreiber Set (50 Stück)', '2', '12,49 EUR'],
        ['Haftnotizen Blockset 100er', '3', '6,97 EUR'],
        ['', '', ''],
        ['Summe netto', '', '40,20 EUR'],
        ['MwSt. 19%', '', '7,64 EUR'],
        ['Rechnungsbetrag (brutto)', '', '47,84 EUR'],
    ]

    table = Table(data, colWidths=[6*cm, 2*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9900')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 5), (-1, -1), 'RIGHT'),
    ]))
    story.append(table)

def create_mahnung_weber(story):
    """5. Mahnung - Mycelium Enterprises an Weber Consulting"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Mycelium Enterprises UG", styles['Title']))
    story.append(Paragraph("MAHNUNG 1. FÄLLIG", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "<b>Zahlungsaufforderung für überfällige Rechnung!</b><br/>"
        "Sehr geehrte Damen und Herren,<br/><br/>"
        "trotz mehrmaliger Aufforderung haben Sie die nachfolgende Rechnung nicht beglichen.<br/>"
        "Wir fordern Sie hiermit auf, den ausstehenden Betrag innerhalb von 7 Tagen zu bezahlen.<br/>",
        styles['Normal']
    ))

    data = [
        ['Rechnungsdetails', ''],
        ['Ursprüngliche Rechnung:', 'RE-EXT-002'],
        ['Rechnungsdatum:', '15.02.2026'],
        ['Fälligkeit original:', '15.03.2026'],
        ['Debitor:', 'Weber Consulting GmbH'],
        ['', ''],
        ['AUSSTEHEND:', '1.200,00 EUR'],
        ['Mahngebühr 5%:', '60,00 EUR'],
        ['FÄLLIG SOFORT:', '1.260,00 EUR'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CC0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -3), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -3), (-1, -1), colors.HexColor('#FFCCCC')),
        ('GRID', (0, 0), (-1, -1), 1, colors.red),
    ]))
    story.append(table)

def create_mietvertrag_nachtrag(story):
    """6. Mietvertrag Nachtrag - neue Miete 490€"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Immobilien Schneider", styles['Title']))
    story.append(Paragraph("Nachtrag zum Mietvertrag", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Mietverhältnis', ''],
        ['Mieter:', 'Anna Müller'],
        ['Immobilie:', 'Rainstraße 42, 76437 Rastatt'],
        ['Wohnungsgröße:', '75 m²'],
        ['', ''],
        ['Änderungen ab 01.05.2026:', ''],
        ['', ''],
        ['Alte Miete (April):', '450,00 EUR'],
        ['NEUE Miete (ab Mai):', '490,00 EUR'],
        ['Mieterhöhung:', '+40,00 EUR'],
        ['', ''],
        ['Nebenkosten (unverändert):', '89,50 EUR'],
        ['Gesamtmiete neu:', '579,50 EUR'],
        ['', ''],
        ['Gültig ab:', '01.05.2026'],
        ['Unterzeichner:', 'Immobilien Schneider GmbH'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#336633')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 8), (-1, 8), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 8), (-1, 8), colors.HexColor('#FFFFCC')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)

def create_kassenbon_edeka(story):
    """7. EDEKA Kassenbon - Bewirtungsbeleg 23,47€"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("EDEKA Gernsbach", styles['Title']))
    story.append(Paragraph("Kassenbon - Bewirtungsbeleg", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Kassenbon', ''],
        ['Filiale:', 'EDEKA Gernsbach'],
        ['Bonummer:', 'KB-20260403-001234'],
        ['Datum:', '03.04.2026'],
        ['Uhrzeit:', '12:45'],
        ['Kassennummer:', '05'],
        ['', ''],
        ['Artikel', 'Betrag'],
        ['Obst & Gemüse', '8,95 EUR'],
        ['Wurst & Käse', '7,53 EUR'],
        ['Bäckerei', '4,99 EUR'],
        ['Getränk', '1,00 EUR'],
        ['', ''],
        ['GESAMT BRUTTO', '23,47 EUR'],
        ['MwSt. (verschiedene Sätze)', '3,47 EUR'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FFC000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#FFFFCC')),
        ('GRID', (0, 0), (-1, -1), 1, colors.gray),
    ]))
    story.append(table)

def create_steuervorauszahlung(story):
    """8. Finanzamt Rastatt - ESt-Vorauszahlung Q2"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Finanzamt Rastatt", styles['Title']))
    story.append(Paragraph("Steuerbescheid - Einkommensteuer Vorauszahlung", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Steuerinformation', ''],
        ['Steuernummer:', '12 345 678 901'],
        ['Name:', 'Müller, Johann'],
        ['Bescheidzeitraum:', '01.04.2026 - 30.06.2026 (Q2 2026)'],
        ['Bescheidnummer:', 'ST-2026-Q2-54321'],
        ['', ''],
        ['ESt-Vorauszahlung Q2 2026', '312,00 EUR'],
        ['Fälligkeit:', '15.04.2026'],
        ['', ''],
        ['Zahlungsart:', 'Dauerauftrag oder Überweisung'],
        ['Bankverbindung:', 'siehe Rückseite'],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 6), (-1, 6), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 6), (-1, 6), colors.HexColor('#E6F0FF')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)

def create_hetzner_gutschein(story):
    """9. Hetzner Online - Gutschrift 10€"""
    styles = getSampleStyleSheet()

    story.append(Paragraph("Hetzner Online GmbH", styles['Title']))
    story.append(Paragraph("Gutschrift / Rechnungskorrektur", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Gutschrift Details', ''],
        ['Rechnungsnummer:', 'GS-2026-042189'],
        ['Kundennummer:', 'HZ-8765432'],
        ['Gutschriftdatum:', '02.04.2026'],
        ['Bezug auf Rechnung:', 'RG-2026-041923'],
        ['', ''],
        ['Grund:', 'Rückerstattung wegen Stornierung Server Downtime'],
        ['', ''],
        ['Gutschrift Brutto:', '10,00 EUR'],
        ['davon MwSt. 19%:', '1,59 EUR'],
        ['Netto-Gutschrift:', '8,41 EUR'],
        ['', ''],
        ['Guthaben wird automatisch verrechnet', ''],
    ]

    table = Table(data, colWidths=[9*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#004B87')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 8), (-1, 9), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 8), (-1, 9), colors.HexColor('#CCFFCC')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)

def create_mediamarkt_privat(story):
    """10. MediaMarkt - Kopfhörer Sony (PRIVAT)"""
    styles = getSampleStyleSheet()

    # Wasserzeichen-ähnlicher Text
    story.append(Paragraph(
        "<b style='color: red; font-size: 16'>⚠ PRIVAT - NICHT BETRIEBLICH ⚠</b>",
        styles['Normal']
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph("MediaMarkt Online", styles['Title']))
    story.append(Paragraph("Bestellbestätigung Einzelhandel", styles['Heading2']))
    story.append(Spacer(1, 0.3*cm))

    data = [
        ['Bestellinformation', ''],
        ['Bestellnummer:', 'MM-2026-034567'],
        ['Bestelldatum:', '01.04.2026'],
        ['Kundenname:', 'Hans Zimmermann'],
        ['', ''],
        ['Artikel', 'Menge', 'Preis'],
        ['Sony WH-1000XM5 Kopfhörer', '1', '279,00 EUR'],
        ['', '', ''],
        ['GESAMTBETRAG (brutto)', '', '279,00 EUR'],
        ['davon MwSt. 19%', '', '44,55 EUR'],
        ['', '', ''],
        ['HINWEIS:', '', ''],
        ['Diese Rechnung dokumentiert einen', '', ''],
        ['Privatankauf und ist NICHT', '', ''],
        ['betrieblich absetzbar.', '', ''],
    ]

    table = Table(data, colWidths=[6*cm, 2*cm, 3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CC0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 8), (-1, 8), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 8), (-1, 8), colors.HexColor('#FFEEEE')),
        ('FONTNAME', (0, 11), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 11), (-1, -1), colors.HexColor('#FFCCCC')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 5), (-1, -1), 'RIGHT'),
    ]))
    story.append(table)

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("[*] Starte P40 Test-Docs Generator...")
    print(f"[D] Output-Verzeichnis: {output_dir}")
    print()

    if not HAS_REPORTLAB:
        print("[E] reportlab nicht installiert!")
        print("   Bitte installieren: pip install reportlab")
        return False

    documents = [
        ("telekom_mobilfunk_apr.pdf", "Deutsche Telekom Mobilfunk", create_telekom_mobilfunk),
        ("axa_kfz_versicherung.pdf", "AXA Kfz-Versicherung", create_axa_kfz),
        ("stadtwerke_gas_q1.pdf", "Stadtwerke Gas Q1", create_stadtwerke_gas),
        ("amazon_bueromaterial.pdf", "Amazon Büromaterial", create_amazon_office),
        ("mahnung_weber.pdf", "Mahnung Weber Consulting", create_mahnung_weber),
        ("mietvertrag_nachtrag.pdf", "Mietvertrag Nachtrag", create_mietvertrag_nachtrag),
        ("kassenbon_edeka.pdf", "EDEKA Kassenbon", create_kassenbon_edeka),
        ("steuervorauszahlung.pdf", "Finanzamt ESt-Vorauszahlung", create_steuervorauszahlung),
        ("gutschein_hetzner.pdf", "Hetzner Gutschrift", create_hetzner_gutschein),
        ("privat_mediamarkt.pdf", "MediaMarkt Kopfhörer (PRIVAT)", create_mediamarkt_privat),
    ]

    created_files = []
    errors = []

    for filename, title, create_func in documents:
        try:
            filepath = create_document_reportlab(filename, title, create_func)
            created_files.append(filepath)
            file_size = os.path.getsize(filepath)
            print(f"[OK] {filename:<35} ({file_size:>6} Bytes)")
        except Exception as e:
            errors.append((filename, str(e)))
            print(f"[FAIL] {filename:<35} FEHLER: {e}")

    print()
    print(f"[SUMMARY] Zusammenfassung:")
    print(f"   [OK] Erfolgreich erstellt: {len(created_files)}")
    print(f"   [FAIL] Fehler: {len(errors)}")
    print()

    if created_files:
        print(f"[PATH] Alle PDFs befinden sich in: {output_dir}")
        print()
        print("[LIST] Generierte Dateien:")
        for filepath in created_files:
            print(f"   - {Path(filepath).name}")

    return len(errors) == 0

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
