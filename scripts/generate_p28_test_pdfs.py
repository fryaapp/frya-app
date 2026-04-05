#!/usr/bin/env python3
"""P-28: Generate 10 test PDFs for FRYA Komplett-Test (korrekte + fehlerhafte Dokumente)."""

import os
import io
import math
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas

W, H = A4
OUT = os.path.join(os.path.dirname(__file__), '..', 'test_pdfs', 'p28')
os.makedirs(OUT, exist_ok=True)

BLUE = HexColor('#003366')
GREY = HexColor('#666666')
LIGHT_GREY = HexColor('#F5F5F5')
RED = HexColor('#CC0000')
ORANGE = HexColor('#F08A3A')
GREEN = HexColor('#2E7D32')


def _header(c, name, addr, color=BLUE):
    c.setFillColor(color)
    c.rect(0, H - 28*mm, W, 28*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 16)
    c.drawString(20*mm, H - 18*mm, name)
    c.setFont('Helvetica', 8)
    c.drawString(20*mm, H - 24*mm, addr)
    return H - 38*mm


def _recipient(c, y, name, street, city):
    c.setFillColor(black)
    c.setFont('Helvetica', 10)
    c.drawString(20*mm, y, name)
    c.drawString(20*mm, y - 5*mm, street)
    c.drawString(20*mm, y - 10*mm, city)
    return y - 22*mm


def _invoice_title(c, y, title, rechnr, datum, faellig=None):
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 14)
    c.drawString(20*mm, y, title)
    y -= 8*mm
    c.setFont('Helvetica', 10)
    c.drawString(20*mm, y, f'Rechnungsnummer: {rechnr}')
    c.drawString(120*mm, y, f'Datum: {datum}')
    if faellig:
        y -= 5*mm
        c.drawString(20*mm, y, f'Zahlungsziel: {faellig}')
    return y - 10*mm


def _table_header(c, y, cols, widths):
    c.setFillColor(BLUE)
    c.rect(20*mm, y - 1*mm, sum(widths), 7*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 9)
    x = 20*mm
    for i, col in enumerate(cols):
        c.drawString(x + 2*mm, y + 2*mm, col)
        x += widths[i]
    return y - 8*mm


def _table_row(c, y, cols, widths, bold=False, bg=None):
    if bg:
        c.setFillColor(bg)
        c.rect(20*mm, y - 1*mm, sum(widths), 6*mm, fill=1, stroke=0)
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', 9)
    c.setFillColor(black)
    x = 20*mm
    for i, col in enumerate(cols):
        c.drawString(x + 2*mm, y + 1*mm, str(col))
        x += widths[i]
    return y - 7*mm


def _footer(c, name, ust_id='', steuernr='', iban='', bic='', hinweis=''):
    c.setStrokeColor(GREY)
    c.setLineWidth(0.3)
    c.line(20*mm, 28*mm, W - 20*mm, 28*mm)
    c.setFillColor(GREY)
    c.setFont('Helvetica', 7)
    y = 25*mm
    c.drawString(20*mm, y, name)
    if ust_id:
        c.drawString(20*mm, y - 4*mm, f'USt-IdNr.: {ust_id}')
    if steuernr:
        c.drawString(80*mm, y - 4*mm, f'Steuernummer: {steuernr}')
    if iban:
        c.drawString(20*mm, y - 8*mm, f'IBAN: {iban}')
    if bic:
        c.drawString(100*mm, y - 8*mm, f'BIC: {bic}')
    if hinweis:
        c.setFont('Helvetica-Oblique', 7)
        c.setFillColor(RED)
        c.drawString(20*mm, y - 12*mm, hinweis)


# ============================================================================
# PDF 1: miete_april.pdf — Immobilien Schneider, 450€ + 19% = 535,50€
# ============================================================================
def gen_miete_april():
    path = os.path.join(OUT, 'miete_april.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Immobilien Schneider GmbH', 'Hauptstraße 12 · 76530 Baden-Baden · Tel: 07221 889900', BLUE)
    y = _recipient(c, y, 'Petra Weber / Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    y = _invoice_title(c, y, 'Rechnung', 'IS-2026-0042', '01.04.2026', '15.04.2026')

    c.setFont('Helvetica-Bold', 10)
    c.drawString(20*mm, y, 'Betreff: Miete April 2026')
    y -= 8*mm

    widths = [90*mm, 30*mm, 35*mm, 30*mm]
    y = _table_header(c, y, ['Beschreibung', 'Menge', 'Einzelpreis', 'Gesamt'], widths)
    y = _table_row(c, y, ['Gewerbemiete April 2026', '1', '450,00 €', '450,00 €'], widths)
    y -= 5*mm

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, '450,00 €')
    y -= 5*mm
    c.drawRightString(175*mm, y, 'zzgl. 19% MwSt:')
    c.drawString(177*mm, y, '85,50 €')
    y -= 1*mm
    c.setStrokeColor(BLUE)
    c.setLineWidth(0.5)
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '535,50 €')

    _footer(c, 'Immobilien Schneider GmbH', ust_id='DE123456789',
            iban='DE89 3704 0044 0532 0130 00', bic='COBADEFFXXX')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 2: strom_swb.pdf — Stadtwerke Baden-Baden, 187,43€ brutto
# ============================================================================
def gen_strom_swb():
    path = os.path.join(OUT, 'strom_swb.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Stadtwerke Baden-Baden GmbH', 'Schneidemühlstr. 1a · 76530 Baden-Baden · www.swb-stadtwerke.de', HexColor('#005A8E'))
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    y = _invoice_title(c, y, 'Energierechnung Q1 2026', 'SWB-2026-1Q-1193', '05.04.2026', '20.04.2026')

    c.setFont('Helvetica', 10)
    c.drawString(20*mm, y, f'Vertragsnummer: SWB-2024-1193 · Zählernummer: 12345678')
    y -= 10*mm

    widths = [90*mm, 30*mm, 35*mm, 30*mm]
    y = _table_header(c, y, ['Leistung', 'Menge/Einheit', 'Einzelpreis', 'Netto'], widths)
    y = _table_row(c, y, ['Stromverbrauch Jan–Mrz 2026', '1.847 kWh', '0,0850 €/kWh', '156,99 €'], widths, bg=LIGHT_GREY)
    y = _table_row(c, y, ['Grundpreis Q1', '1 Quartal', '8,75 €/Mon.', '26,25 €'], widths)
    y -= 5*mm

    netto = 156.99 + 26.25
    mwst = round(netto * 0.19, 2)
    brutto = round(netto + mwst, 2)

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, f'{netto:.2f} €'.replace('.', ','))
    y -= 5*mm
    c.drawRightString(175*mm, y, 'zzgl. 19% MwSt:')
    c.drawString(177*mm, y, f'{mwst:.2f} €'.replace('.', ','))
    y -= 1*mm
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '187,43 €')

    _footer(c, 'Stadtwerke Baden-Baden GmbH', ust_id='DE987654321',
            iban='DE12 6604 0085 0207 6750 00', bic='COBADEFFXXX')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 3: coaching_einnahme.pdf — Rechnung VON Petra Weber AN Mycelium (Kleinunternehmer)
# ============================================================================
def gen_coaching_einnahme():
    path = os.path.join(OUT, 'coaching_einnahme.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Petra Weber — Business Coaching', 'Gartenweg 5 · 76131 Karlsruhe · petra.weber@example.de', GREEN)
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Hauptstraße 42', '76133 Karlsruhe')
    y = _invoice_title(c, y, 'Rechnung', 'PW-2026-007', '02.04.2026', '02.05.2026')

    c.setFont('Helvetica-Bold', 10)
    c.drawString(20*mm, y, 'Coaching-Paket: Business Development')
    y -= 10*mm

    widths = [90*mm, 25*mm, 35*mm, 35*mm]
    y = _table_header(c, y, ['Leistung', 'Stunden', 'Stundensatz', 'Gesamt'], widths)
    y = _table_row(c, y, ['Business Coaching (Einzelsitzungen)', '5 h', '120,00 €', '600,00 €'], widths)
    y -= 8*mm

    c.setFillColor(LIGHT_GREY)
    c.rect(20*mm, y - 2*mm, W - 40*mm, 14*mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(22*mm, y + 8*mm, 'Gesamtbetrag: 600,00 €')
    c.setFont('Helvetica', 9)
    c.drawString(22*mm, y + 2*mm, 'Kein Steuerausweis gemäß §19 UStG (Kleinunternehmerregelung)')
    y -= 20*mm

    c.setFont('Helvetica', 9)
    c.drawString(20*mm, y, 'Zahlbar innerhalb von 30 Tagen auf das unten angegebene Konto.')

    _footer(c, 'Petra Weber · Einzelunternehmen', steuernr='12345/67890',
            iban='DE45 5001 0517 5407 3249 31', bic='INGDDEFFXXX',
            hinweis='Gemäß §19 UStG wird keine Umsatzsteuer berechnet.')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 4: hetzner_server.pdf — Hetzner Online GmbH, CX33 April 2026, 42,34€
# ============================================================================
def gen_hetzner_server():
    path = os.path.join(OUT, 'hetzner_server.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Hetzner Online GmbH', 'Industriestr. 25 · 91710 Gunzenhausen · www.hetzner.com', HexColor('#D50000'))
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    y = _invoice_title(c, y, 'Rechnung', 'HZ-2026-04-887432', '01.04.2026', '15.04.2026')

    c.setFont('Helvetica', 9)
    c.drawString(20*mm, y, 'Kundennummer: K-229341 · Projekt: mycelium-prod')
    y -= 10*mm
    c.setFont('Helvetica', 8)
    c.setFillColor(ORANGE)
    c.drawString(20*mm, y, '(Wiederkehrende Rechnung — gleicher Betrag jeden Monat)')
    c.setFillColor(black)
    y -= 8*mm

    widths = [80*mm, 30*mm, 30*mm, 30*mm, 15*mm]
    y = _table_header(c, y, ['Produkt', 'Abrechnungszeitraum', 'Netto', 'MwSt', 'Ges.'], widths)
    y = _table_row(c, y, ['Server CX33', 'Apr 2026', '35,59 €', '6,76 €', '42,34 €'], widths, bg=LIGHT_GREY)
    y -= 5*mm

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, '35,59 €')
    y -= 5*mm
    c.drawRightString(175*mm, y, 'zzgl. 19% MwSt:')
    c.drawString(177*mm, y, '6,76 €')
    y -= 1*mm
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '42,34 €')

    _footer(c, 'Hetzner Online GmbH', ust_id='DE812871812',
            iban='DE20 7004 0045 0770 0799 00', bic='COBADEFFXXX')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 5: bahncard_rechnung.pdf — Deutsche Bahn AG, BahnCard Business 100, 4.027,00€, 7% MwSt
# ============================================================================
def gen_bahncard_rechnung():
    path = os.path.join(OUT, 'bahncard_rechnung.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Deutsche Bahn AG', 'Stephensonstraße 1 · 60326 Frankfurt am Main · www.bahn.de', HexColor('#F01414'))
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    y = _invoice_title(c, y, 'Rechnung', 'DB-BC-2026-00192837', '28.03.2026', '12.04.2026')

    c.setFont('Helvetica-Bold', 10)
    c.drawString(20*mm, y, 'Ihr Produkt: BahnCard Business 100 (1. Klasse)')
    y -= 8*mm
    c.setFont('Helvetica', 9)
    c.drawString(20*mm, y, 'Gültigkeitszeitraum: 01.04.2026 – 31.03.2027')
    y -= 10*mm

    widths = [90*mm, 30*mm, 35*mm, 30*mm]
    y = _table_header(c, y, ['Produkt', 'Gültigkeit', 'Netto', 'Gesamt'], widths)
    y = _table_row(c, y, ['BahnCard Business 100, 1. Kl.', '12 Monate', '3.763,55 €', '4.027,00 €'], widths, bg=LIGHT_GREY)
    y -= 5*mm

    netto = 3763.55
    mwst = round(netto * 0.07, 2)
    brutto = 4027.00

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, f'{netto:,.2f} €'.replace('.', ',').replace(',', '.', 1))
    y -= 5*mm
    c.setFillColor(RED)
    c.drawRightString(175*mm, y, 'zzgl. ermäßigt 7% MwSt (§12 Abs. 2 UStG):')
    c.setFillColor(black)
    c.drawString(177*mm, y, '263,45 €')
    y -= 1*mm
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '4.027,00 €')

    _footer(c, 'Deutsche Bahn AG', ust_id='DE811101840',
            iban='DE29 5007 0010 0000 7878 00', bic='DEUTDEDB500')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 6: office365_abo.pdf — Microsoft Ireland, 12,10€/Monat, Reverse Charge §13b
# ============================================================================
def gen_office365_abo():
    path = os.path.join(OUT, 'office365_abo.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Microsoft Ireland Operations Ltd.', 'One Microsoft Place · South County Business Park · Leopardstown · Dublin 18', HexColor('#0078D4'))
    y = _recipient(c, y, 'Mycelium Enterprises UG (Rechnungsempfänger)', 'Gartenweg 5', '76131 Karlsruhe, Deutschland')
    y = _invoice_title(c, y, 'Tax Invoice / Rechnung', 'E8600000-2026-0401', '01.04.2026', '01.05.2026')

    c.setFont('Helvetica', 9)
    c.drawString(20*mm, y, 'Vendor VAT ID: IE8256796U | Customer VAT ID: DE345678901')
    y -= 10*mm

    widths = [90*mm, 30*mm, 35*mm, 30*mm]
    y = _table_header(c, y, ['Produkt/Dienst', 'Zeitraum', 'Preis/Einheit', 'Gesamt'], widths)
    y = _table_row(c, y, ['Microsoft 365 Business Basic', 'Apr 2026', '12,10 €', '12,10 €'], widths, bg=LIGHT_GREY)
    y -= 8*mm

    c.setFillColor(LIGHT_GREY)
    c.rect(20*mm, y - 2*mm, W - 40*mm, 18*mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(22*mm, y + 12*mm, 'Rechnungsbetrag: 12,10 €')
    c.setFont('Helvetica', 8)
    c.setFillColor(RED)
    c.drawString(22*mm, y + 6*mm, 'Reverse Charge: Steuerschuldnerschaft des Leistungsempfängers gemäß §13b UStG')
    c.drawString(22*mm, y + 1*mm, 'Der Leistungsempfänger schuldet die Umsatzsteuer (0% in dieser Rechnung ausgewiesen).')
    y -= 28*mm

    _footer(c, 'Microsoft Ireland Operations Ltd.',
            hinweis='Reverse Charge §13b UStG — Steuerschuldner ist der Leistungsempfänger')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 7: falsche_mwst.pdf — Rechnung mit 23% MwSt (ungültig in DE)
# ============================================================================
def gen_falsche_mwst():
    path = os.path.join(OUT, 'falsche_mwst.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Testlieferant GmbH', 'Musterstraße 1 · 10115 Berlin', HexColor('#555555'))
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    y = _invoice_title(c, y, 'Rechnung', 'TL-2026-0099', '01.04.2026', '15.04.2026')

    c.setFont('Helvetica', 9)
    c.drawString(20*mm, y, '⚠ TESTZWECK: Ungültiger MwSt-Satz von 23% (nur in Polen/Griechenland gültig)')
    c.setFillColor(RED)
    c.drawString(20*mm, y - 5*mm, 'DIESE RECHNUNG ENTHÄLT EINEN FEHLERHAFTEN STEUERSATZ!')
    c.setFillColor(black)
    y -= 15*mm

    widths = [90*mm, 30*mm, 35*mm, 30*mm]
    y = _table_header(c, y, ['Beschreibung', 'Menge', 'Netto', 'Gesamt'], widths)
    y = _table_row(c, y, ['Beratungsleistung März 2026', '1', '1.000,00 €', '1.000,00 €'], widths)
    y -= 5*mm

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, '1.000,00 €')
    y -= 5*mm
    c.setFillColor(RED)
    c.setFont('Helvetica-Bold', 9)
    c.drawRightString(175*mm, y, 'zzgl. 23% MwSt:')  # FALSCH! Nicht in DE
    c.drawString(177*mm, y, '230,00 €')
    c.setFillColor(black)
    y -= 1*mm
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '1.230,00 €')

    _footer(c, 'Testlieferant GmbH', ust_id='DE999999999',
            iban='DE00 0000 0000 0000 0000 00',
            hinweis='FEHLER: 23% MwSt ist in Deutschland nicht zulässig! (DE: 19% / 7%)')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 8: doppelte_rechnung.pdf — Exakt gleiche Rechnungsnr wie hetzner_server.pdf
# ============================================================================
def gen_doppelte_rechnung():
    path = os.path.join(OUT, 'doppelte_rechnung.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'Hetzner Online GmbH', 'Industriestr. 25 · 91710 Gunzenhausen · www.hetzner.com', HexColor('#D50000'))
    y = _recipient(c, y, 'Mycelium Enterprises UG', 'Gartenweg 5', '76131 Karlsruhe')
    # GLEICHE Rechnungsnummer wie PDF 4!
    y = _invoice_title(c, y, 'Rechnung (DUPLIKAT)', 'HZ-2026-04-887432', '01.04.2026', '15.04.2026')

    c.setFillColor(RED)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(20*mm, y, '⚠ TESTZWECK: Diese Rechnung hat dieselbe Nummer wie eine bereits eingereichte Rechnung!')
    c.setFillColor(black)
    y -= 12*mm

    widths = [80*mm, 30*mm, 30*mm, 30*mm, 15*mm]
    y = _table_header(c, y, ['Produkt', 'Abrechnungszeitraum', 'Netto', 'MwSt', 'Ges.'], widths)
    y = _table_row(c, y, ['Server CX33', 'Apr 2026', '35,59 €', '6,76 €', '42,34 €'], widths, bg=LIGHT_GREY)
    y -= 5*mm

    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '42,34 €')

    _footer(c, 'Hetzner Online GmbH', ust_id='DE812871812',
            iban='DE20 7004 0045 0770 0799 00', bic='COBADEFFXXX',
            hinweis='DUPLIKAT-TEST: Rechnungsnr. HZ-2026-04-887432 bereits vorhanden!')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 9: unleserlich.pdf — Extrem niedrige Qualität, schief, verwaschen
# ============================================================================
def gen_unleserlich():
    """Generates a low-quality, skewed, blurry-looking PDF for OCR stress test."""
    path = os.path.join(OUT, 'unleserlich.pdf')
    # Use very small page and low info density to simulate bad scan
    c = canvas.Canvas(path, pagesize=A4)

    # Draw skewed/noisy background
    c.setFillColor(HexColor('#E8E0D5'))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Simulate scan artifacts with overlapping lines
    c.setStrokeColor(HexColor('#C8C0B8'))
    c.setLineWidth(0.3)
    for i in range(0, int(H), 8):
        c.line(0, i, W, i)

    # Random noise rectangles (simulate scan artifacts)
    import random
    random.seed(42)
    c.setFillColor(HexColor('#D5CEC7'))
    for _ in range(60):
        x = random.randint(0, int(W))
        y = random.randint(0, int(H))
        w = random.randint(2, 15)
        h = random.randint(1, 4)
        c.rect(x, y, w, h, fill=1, stroke=0)

    # Save current state and rotate to simulate skewed scan
    c.saveState()
    c.translate(W/2, H/2)
    c.rotate(-3.5)  # 3.5 degree skew
    c.translate(-W/2, -H/2)

    # Draw faded/blurry text with reduced contrast
    c.setFillColor(HexColor('#4A4540'))

    c.setFont('Helvetica-Bold', 13)
    c.drawString(20*mm, H - 35*mm, 'Stadtwerke Baden-Baden GmbH')
    c.setFont('Helvetica', 9)
    c.drawString(20*mm, H - 42*mm, 'Schneidemu\u0308hlstr. 1a · 76530 Baden-Baden')

    c.setFont('Helvetica', 10)
    c.drawString(20*mm, H - 60*mm, 'Rechnung Nr: SWB-2025-12-5544')
    c.drawString(20*mm, H - 67*mm, 'Datum: 05.01.2026')
    c.drawString(20*mm, H - 80*mm, 'Kunde: Mycelium Enterprises UG')

    # Very faint middle text
    c.setFillColor(HexColor('#7A7570'))
    c.setFont('Helvetica', 9)
    c.drawString(20*mm, H - 110*mm, 'Strom Januar 2026')
    c.drawString(20*mm, H - 118*mm, 'Verbrauch: 612 kWh')
    c.drawString(20*mm, H - 126*mm, 'Preis: 0,0850 €/kWh = 52,02 €')
    c.drawString(20*mm, H - 134*mm, 'Grundpreis: 8,75 €')
    c.drawString(20*mm, H - 142*mm, 'Netto: 60,77 €')
    c.drawString(20*mm, H - 150*mm, '19% MwSt: 11,55 €')

    c.setFillColor(HexColor('#4A4540'))
    c.setFont('Helvetica-Bold', 11)
    c.drawString(20*mm, H - 162*mm, 'Gesamt: 72,32 €')

    # Add more noise and smearing
    c.setFillColor(HexColor('#B8B0A8'))
    for _ in range(30):
        x = random.randint(20, int(W - 20))
        y = random.randint(int(H*0.2), int(H*0.85))
        c.setFont('Helvetica', random.randint(6, 9))
        c.drawString(x, y, chr(random.randint(65, 122)))

    c.restoreState()

    c.setFont('Helvetica', 6)
    c.setFillColor(HexColor('#AAA49E'))
    c.drawString(20*mm, 10*mm, 'Scan-Qualität: 72dpi · Automatisch digitalisiert')

    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# PDF 10: gemischt_privat.pdf — PlayStation 5, 499€ Privatkauf
# ============================================================================
def gen_gemischt_privat():
    path = os.path.join(OUT, 'gemischt_privat.pdf')
    c = canvas.Canvas(path, pagesize=A4)
    y = _header(c, 'MediaMarkt Saturn Retail Group', 'Am Münchner Tor 1 · 80939 München · www.mediamarkt.de', HexColor('#CC0000'))
    y = _recipient(c, y, 'Petra Weber', 'Gartenweg 5', '76131 Karlsruhe')  # An PRIVAT, nicht an Firma
    y = _invoice_title(c, y, 'Kassenbon / Quittung', 'MM-KA-2026-038291', '01.04.2026')

    c.setFont('Helvetica', 9)
    c.setFillColor(ORANGE)
    c.drawString(20*mm, y, '⚠ TESTZWECK: Privatkauf — kein Geschäftsbezug!')
    c.setFillColor(black)
    y -= 10*mm

    widths = [90*mm, 25*mm, 35*mm, 35*mm]
    y = _table_header(c, y, ['Artikel', 'Menge', 'Preis/Stk', 'Gesamt'], widths)
    y = _table_row(c, y, ['Sony PlayStation 5 (Disc Edition)', '1', '449,99 €', '449,99 €'], widths, bg=LIGHT_GREY)
    y = _table_row(c, y, ['DualSense Controller', '1', '49,99 €', '49,99 €'], widths)
    y -= 5*mm

    netto = (449.99 + 49.99) / 1.19
    mwst = (449.99 + 49.99) - netto

    c.setFont('Helvetica', 9)
    c.drawRightString(175*mm, y, 'Nettobetrag:')
    c.drawString(177*mm, y, f'{netto:.2f} €'.replace('.', ','))
    y -= 5*mm
    c.drawRightString(175*mm, y, 'inkl. 19% MwSt:')
    c.drawString(177*mm, y, f'{mwst:.2f} €'.replace('.', ','))
    y -= 1*mm
    c.line(145*mm, y, W - 20*mm, y)
    y -= 4*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(175*mm, y, 'Gesamtbetrag:')
    c.drawString(177*mm, y, '499,98 €')

    y -= 15*mm
    c.setFillColor(HexColor('#FFF3CD'))
    c.rect(20*mm, y - 5*mm, W - 40*mm, 14*mm, fill=1, stroke=0)
    c.setFillColor(HexColor('#856404'))
    c.setFont('Helvetica-Bold', 9)
    c.drawString(23*mm, y + 5*mm, '🎮 Privatanschaffung — kein Geschäftsbezug erkennbar')
    c.setFont('Helvetica', 8)
    c.drawString(23*mm, y, 'Empfänger: Petra Weber (privat), kein Firmenname auf Rechnung')

    _footer(c, 'MediaMarkt Saturn Retail Group GmbH', ust_id='DE129273380',
            iban='DE91 7004 0048 0440 1001 00')
    c.save()
    print(f'OK: {path}')
    return path


# ============================================================================
# MAIN
# ============================================================================
if __name__ == '__main__':
    print(f'\nOutput: {OUT}\n')
    pdfs = [
        gen_miete_april(),
        gen_strom_swb(),
        gen_coaching_einnahme(),
        gen_hetzner_server(),
        gen_bahncard_rechnung(),
        gen_office365_abo(),
        gen_falsche_mwst(),
        gen_doppelte_rechnung(),
        gen_unleserlich(),
        gen_gemischt_privat(),
    ]
    print(f'\n{len(pdfs)}/10 PDFs erstellt in {OUT}')
    for p in pdfs:
        size_kb = os.path.getsize(p) // 1024
        print(f'  {os.path.basename(p)} ({size_kb} KB)')
