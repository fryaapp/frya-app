"""Generiert eine grosse Test-PDF mit 22 realistischen deutschen Belegen,
getrennt durch Paperless-NGX Trennseiten (PATCHT-Barcode).

Jeder Beleg sieht aus wie ein eingescannter Beleg — leicht grauer Hintergrund,
verschiedene Schriftarten, unterschiedliche Layouts.

Belegtypen: Rechnungen, Gutschriften, Quittungen, Mahnungen, Briefe,
Versicherungsschreiben, Kontoauszuege, Gehaltsabrechnungen, Vertraege.
"""
from __future__ import annotations

import io
import os
import random
import string
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Table, TableStyle

W, H = A4  # 595.27, 841.89

# ── Paperless-NGX Trennseite ────────────────────────────────────────────────

def draw_paperless_separator(c: canvas.Canvas, asn: int):
    """Zeichnet eine Paperless-NGX Trennseite mit ASN-Barcode (Code128)."""
    import barcode
    from barcode.writer import ImageWriter

    c.setFillColor(colors.white)
    c.rect(0, 0, W, H, fill=1)

    # Grosser Titel
    c.setFont('Helvetica-Bold', 28)
    c.setFillColor(colors.Color(0.3, 0.3, 0.3))
    c.drawCentredString(W / 2, H - 120, 'PAPERLESS-NGX')
    c.setFont('Helvetica', 16)
    c.drawCentredString(W / 2, H - 150, 'Dokumenten-Trennseite')

    # Trennlinie
    c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
    c.setLineWidth(2)
    c.line(50, H - 170, W - 50, H - 170)

    # ASN-Barcode (Code128)
    asn_str = f'ASN{asn:05d}'
    code128 = barcode.get('code128', asn_str, writer=ImageWriter())
    buf = io.BytesIO()
    code128.write(buf, options={'write_text': True, 'module_width': 0.4, 'module_height': 20, 'font_size': 14, 'text_distance': 5})
    buf.seek(0)

    from reportlab.lib.utils import ImageReader
    img = ImageReader(buf)
    c.drawImage(img, W / 2 - 120, H / 2 - 30, width=240, height=80)

    # Hinweistext
    c.setFont('Helvetica', 11)
    c.setFillColor(colors.Color(0.5, 0.5, 0.5))
    c.drawCentredString(W / 2, H / 2 - 70, f'Dieses Blatt trennt Dokument #{asn} vom naechsten.')
    c.drawCentredString(W / 2, H / 2 - 90, 'Bitte nicht entfernen — wird automatisch erkannt.')

    # Scherenlinie unten
    c.setStrokeColor(colors.Color(0.8, 0.8, 0.8))
    c.setDash(6, 4)
    c.line(30, 100, W - 30, 100)
    c.setDash()  # Reset
    c.setFont('Helvetica', 9)
    c.drawCentredString(W / 2, 85, 'hier abtrennen')

    c.showPage()


# ── Beleg-Generatoren ────────────────────────────────────────────────────────

FIRMEN = [
    ('Buero Discount GmbH', 'Industriestr. 12, 76137 Karlsruhe', 'DE123456789'),
    ('Software Solutions GmbH', 'Berliner Allee 45, 40212 Duesseldorf', 'DE987654321'),
    ('Allianz Versicherungs-AG', 'Koeniginstr. 28, 80802 Muenchen', 'DE111222333'),
    ('Telekom Deutschland GmbH', 'Friedrich-Ebert-Allee 140, 53113 Bonn', 'DE444555666'),
    ('Aral Tankstelle Gernsbach', 'Hauptstr. 8, 76593 Gernsbach', 'DE777888999'),
    ('Gasthaus Zum Hirsch', 'Marktplatz 3, 76530 Baden-Baden', 'DE222333444'),
    ('Amazon EU S.a r.l.', '5 Rue Plaetis, L-2338 Luxemburg', 'LU19647148'),
    ('IONOS SE', 'Elgendorfer Str. 57, 56410 Montabaur', 'DE312225498'),
    ('Hetzner Online GmbH', 'Industriestr. 25, 91710 Gunzenhausen', 'DE812871812'),
    ('DB Fernverkehr AG', 'Stephensonstr. 1, 60326 Frankfurt', 'DE813674913'),
    ('DHL Paket GmbH', 'Schildhornstr. 36, 12163 Berlin', 'DE812627356'),
    ('IKEA Deutschland GmbH', 'Am Wandersmann 2-4, 65719 Hofheim', 'DE811289081'),
    ('Vodafone GmbH', 'Ferdinand-Braun-Platz 1, 40549 Duesseldorf', 'DE122265423'),
    ('HUK-COBURG Versicherung', 'Bahnhofsplatz, 96444 Coburg', 'DE133456789'),
    ('Sparkasse Karlsruhe', 'Kaiserstr. 223, 76133 Karlsruhe', ''),
    ('AOK Baden-Wuerttemberg', 'Presselstr. 19, 70191 Stuttgart', ''),
    ('Finanzamt Karlsruhe-Stadt', 'Schlossplatz 14, 76131 Karlsruhe', ''),
    ('IHK Karlsruhe', 'Lammstr. 13-17, 76133 Karlsruhe', 'DE143504785'),
    ('Stadtwerke Karlsruhe', 'Daxlander Str. 72, 76185 Karlsruhe', 'DE143507722'),
    ('MediaMarkt Karlsruhe', 'Durlacher Allee 109, 76131 Karlsruhe', 'DE811432117'),
    ('Lidl Dienstleistung GmbH', 'Stiftsbergstr. 1, 74172 Neckarsulm', 'DE814526423'),
    ('Edeka Suedwest', 'Edekastr. 1, 77656 Offenburg', 'DE142305619'),
]

def _rand_date(days_back=180):
    d = date.today() - timedelta(days=random.randint(1, days_back))
    return d.strftime('%d.%m.%Y')

def _rand_re():
    return f'RE-{random.randint(2025, 2026)}-{random.randint(10000, 99999)}'

def _eur(amount):
    return f'{amount:,.2f} EUR'.replace(',', 'X').replace('.', ',').replace('X', '.')

def _gray_bg(c: canvas.Canvas):
    """Leicht grauer Hintergrund — wie eingescannt."""
    c.setFillColor(colors.Color(0.96, 0.95, 0.94))
    c.rect(0, 0, W, H, fill=1)

def _scan_noise(c: canvas.Canvas):
    """Simuliert leichtes Scan-Rauschen mit Punkten."""
    c.setFillColor(colors.Color(0.88, 0.87, 0.86))
    for _ in range(random.randint(5, 20)):
        x = random.uniform(20, W - 20)
        y = random.uniform(20, H - 20)
        r = random.uniform(0.3, 1.2)
        c.circle(x, y, r, fill=1, stroke=0)


def draw_rechnung(c: canvas.Canvas, idx: int):
    """Standard-Rechnung mit Positionen."""
    firma = FIRMEN[idx % len(FIRMEN)]
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    # Absender
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(colors.Color(0.15, 0.15, 0.15))
    c.drawString(50, y, firma[0])
    y -= 18
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, firma[1])
    y -= 12
    if firma[2]:
        c.drawString(50, y, f'USt-IdNr.: {firma[2]}')
    y -= 40

    # Empfaenger
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(50, y, 'An:')
    y -= 15
    c.setFont('Helvetica', 11)
    c.drawString(50, y, 'Maze - Mycelium Enterprises UG')
    y -= 14
    c.setFont('Helvetica', 10)
    c.drawString(50, y, 'Waldstr. 42, 76133 Karlsruhe')
    y -= 40

    # Rechnungsnummer + Datum
    re_nr = _rand_re()
    re_datum = _rand_date()
    faellig = _rand_date(30)
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(colors.Color(0.1, 0.1, 0.1))
    c.drawString(50, y, 'RECHNUNG')
    y -= 24
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.Color(0.3, 0.3, 0.3))
    c.drawString(50, y, f'Rechnungsnummer: {re_nr}')
    c.drawString(350, y, f'Datum: {re_datum}')
    y -= 16
    c.drawString(50, y, f'Faellig bis: {faellig}')
    y -= 30

    # Positionen
    netto_gesamt = 0
    positionen = random.randint(1, 5)
    items = []
    for p in range(positionen):
        beschreibung = random.choice([
            'Bueroartikel Standardpaket', 'Hosting monatlich', 'Druckerpatronen 4er-Set',
            'Beratungsleistung 2h', 'Software-Lizenz jaehrlich', 'Versandkosten',
            'Wartungsvertrag Q1', 'Cloud-Speicher 100GB', 'Telefonanlage Miete',
            'Schreibtischstuhl ergonomisch', 'Monitor 27" 4K', 'USB-C Hub',
            'Buchhaltungssoftware', 'Domain-Registrierung', 'SSL-Zertifikat',
        ])
        menge = random.randint(1, 10)
        einzelpreis = round(random.uniform(9.99, 499.99), 2)
        netto = round(menge * einzelpreis, 2)
        netto_gesamt += netto
        items.append([str(p + 1), beschreibung, str(menge), _eur(einzelpreis), _eur(netto)])

    # Tabelle
    header = ['Pos', 'Beschreibung', 'Menge', 'Einzelpreis', 'Gesamt']
    table_data = [header] + items
    col_widths = [30, 220, 50, 80, 80]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.2)),
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.9, 0.89, 0.88)),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.7, 0.7, 0.7)),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    tw, th = t.wrap(0, 0)
    t.drawOn(c, 50, y - th)
    y = y - th - 20

    # Summen
    mwst_satz = random.choice([7.0, 19.0])
    mwst = round(netto_gesamt * mwst_satz / 100, 2)
    brutto = round(netto_gesamt + mwst, 2)

    c.setFont('Helvetica', 10)
    c.drawRightString(W - 50, y, f'Netto: {_eur(netto_gesamt)}')
    y -= 16
    c.drawRightString(W - 50, y, f'MwSt. {mwst_satz:.0f}%: {_eur(mwst)}')
    y -= 16
    c.setFont('Helvetica-Bold', 12)
    c.drawRightString(W - 50, y, f'Gesamtbetrag: {_eur(brutto)}')
    y -= 30

    # Bankverbindung
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.Color(0.5, 0.5, 0.5))
    c.drawString(50, 80, f'Bankverbindung: {firma[0]} | IBAN: DE89 3704 0044 {random.randint(1000, 9999)} {random.randint(1000, 9999)} 00 | BIC: COBADEFFXXX')
    c.drawString(50, 68, f'Bitte geben Sie bei der Ueberweisung die Rechnungsnummer {re_nr} als Verwendungszweck an.')

    c.showPage()


def draw_gutschrift(c: canvas.Canvas, idx: int):
    """Gutschrift / Korrekturrechnung."""
    firma = FIRMEN[idx % len(FIRMEN)]
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(colors.Color(0.15, 0.15, 0.15))
    c.drawString(50, y, firma[0])
    y -= 18
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, firma[1])
    y -= 60

    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(colors.Color(0.0, 0.5, 0.0))
    c.drawString(50, y, 'GUTSCHRIFT')
    y -= 24
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.Color(0.3, 0.3, 0.3))
    c.drawString(50, y, f'Gutschrift-Nr.: GS-{random.randint(2025, 2026)}-{random.randint(1000, 9999)}')
    c.drawString(350, y, f'Datum: {_rand_date()}')
    y -= 16
    c.drawString(50, y, f'Bezug: Rechnung {_rand_re()}')
    y -= 40

    betrag = round(random.uniform(15.0, 250.0), 2)
    c.setFont('Helvetica', 11)
    c.drawString(50, y, f'Wir schreiben Ihnen folgenden Betrag gut:')
    y -= 30
    c.setFont('Helvetica-Bold', 14)
    c.drawString(50, y, f'Gutschriftbetrag: -{_eur(betrag)}')
    y -= 30
    c.setFont('Helvetica', 10)
    c.drawString(50, y, 'Der Betrag wird mit der naechsten Rechnung verrechnet.')

    c.showPage()


def draw_quittung(c: canvas.Canvas, idx: int):
    """Kassenbon / Quittung."""
    firma = FIRMEN[idx % len(FIRMEN)]
    _gray_bg(c)
    _scan_noise(c)

    y = H - 80
    c.setFont('Courier-Bold', 14)
    c.setFillColor(colors.Color(0.1, 0.1, 0.1))
    c.drawCentredString(W / 2, y, firma[0])
    y -= 14
    c.setFont('Courier', 9)
    c.drawCentredString(W / 2, y, firma[1])
    y -= 14
    if firma[2]:
        c.drawCentredString(W / 2, y, f'USt-IdNr.: {firma[2]}')
    y -= 25

    c.setFont('Courier-Bold', 12)
    c.drawCentredString(W / 2, y, 'QUITTUNG / KASSENBON')
    y -= 20
    c.setFont('Courier', 10)
    c.drawCentredString(W / 2, y, f'Datum: {_rand_date()}  Uhrzeit: {random.randint(8,21)}:{random.randint(10,59):02d}')
    y -= 20
    c.drawCentredString(W / 2, y, '-' * 40)
    y -= 18

    # Positionen
    total = 0
    for _ in range(random.randint(2, 8)):
        artikel = random.choice([
            'Kaffee', 'Sandwich', 'Wasser 0.5L', 'Baguette', 'Apfelsaft',
            'Diesel 45.3L', 'Super E10 38.1L', 'Autowaesche', 'Zeitschrift',
            'Schraube M8x40', 'Klebeband', 'Batterien AA 4er', 'Gluehbirne LED',
        ])
        preis = round(random.uniform(0.99, 89.99), 2)
        total += preis
        c.setFont('Courier', 9)
        c.drawString(120, y, f'{artikel:<25s} {preis:>8.2f} EUR')
        y -= 14

    y -= 6
    c.drawCentredString(W / 2, y, '-' * 40)
    y -= 16
    c.setFont('Courier-Bold', 11)
    c.drawString(120, y, f'{"TOTAL":<25s} {total:>8.2f} EUR')
    y -= 14
    c.setFont('Courier', 9)
    mwst = round(total * 19 / 119, 2)
    c.drawString(120, y, f'{"davon MwSt. 19%":<25s} {mwst:>8.2f} EUR')
    y -= 20
    zahlung = random.choice(['BAR', 'EC-KARTE', 'KREDITKARTE'])
    c.drawCentredString(W / 2, y, f'Bezahlt: {zahlung}')
    y -= 18
    c.drawCentredString(W / 2, y, 'Vielen Dank fuer Ihren Einkauf!')

    c.showPage()


def draw_mahnung(c: canvas.Canvas, idx: int):
    """Zahlungserinnerung / Mahnung."""
    firma = FIRMEN[idx % len(FIRMEN)]
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(colors.Color(0.15, 0.15, 0.15))
    c.drawString(50, y, firma[0])
    y -= 18
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, firma[1])
    y -= 60

    stufe = random.choice(['1.', '2.', '3.'])
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(colors.Color(0.8, 0.0, 0.0))
    c.drawString(50, y, f'{stufe} MAHNUNG')
    y -= 24
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.Color(0.3, 0.3, 0.3))
    re_nr = _rand_re()
    c.drawString(50, y, f'Bezug: Rechnung {re_nr} vom {_rand_date(90)}')
    c.drawString(350, y, f'Datum: {_rand_date(14)}')
    y -= 30

    betrag = round(random.uniform(50.0, 2500.0), 2)
    c.setFont('Helvetica', 11)
    c.drawString(50, y, f'Sehr geehrte Damen und Herren,')
    y -= 20
    c.drawString(50, y, f'trotz unserer Zahlungserinnerung konnten wir leider noch')
    y -= 16
    c.drawString(50, y, f'keinen Zahlungseingang fuer o.g. Rechnung feststellen.')
    y -= 30
    c.setFont('Helvetica-Bold', 12)
    c.drawString(50, y, f'Offener Betrag: {_eur(betrag)}')
    y -= 16
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f'Bitte ueberweisen Sie den Betrag innerhalb von 7 Tagen.')

    c.showPage()


def draw_brief(c: canvas.Canvas, idx: int):
    """Allgemeiner Geschaeftsbrief."""
    firma = FIRMEN[idx % len(FIRMEN)]
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.Color(0.15, 0.15, 0.15))
    c.drawString(50, y, firma[0])
    y -= 16
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, firma[1])
    y -= 60

    c.setFont('Helvetica', 10)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(50, y, 'Maze - Mycelium Enterprises UG')
    y -= 14
    c.drawString(50, y, 'Waldstr. 42')
    y -= 14
    c.drawString(50, y, '76133 Karlsruhe')
    y -= 30
    c.drawRightString(W - 50, y, f'Datum: {_rand_date()}')
    y -= 30

    betreff = random.choice([
        'Ihre Anfrage vom letzten Monat',
        'Vertragsaenderung zum naechsten Quartal',
        'Bestaetigung Ihrer Kuendigung',
        'Einladung zur Jahreshauptversammlung',
        'Aenderung unserer AGB zum 01.07.2026',
        'Mitteilung: Neue Kontoverbindung',
        'Beitragsanpassung ab 2026',
    ])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(50, y, f'Betreff: {betreff}')
    y -= 30

    c.setFont('Helvetica', 10)
    c.drawString(50, y, 'Sehr geehrte Damen und Herren,')
    y -= 20

    text_lines = [
        'vielen Dank fuer Ihr Schreiben. Wir haben Ihr Anliegen',
        'geprueft und moechten Ihnen folgendes mitteilen:',
        '',
        'Nach eingehender Pruefung koennen wir Ihrem Wunsch',
        'entsprechen. Die Aenderungen treten zum naechsten',
        'Monatsersten in Kraft.',
        '',
        'Sollten Sie weitere Fragen haben, stehen wir Ihnen',
        'gerne zur Verfuegung.',
        '',
        'Mit freundlichen Gruessen',
        '',
        firma[0],
    ]
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 14

    c.showPage()


def draw_kontoauszug(c: canvas.Canvas, idx: int):
    """Bank-Kontoauszug."""
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(colors.Color(0.1, 0.1, 0.1))
    c.drawString(50, y, 'Sparkasse Karlsruhe')
    y -= 18
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, 'Kaiserstr. 223, 76133 Karlsruhe')
    y -= 40

    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.Color(0.1, 0.1, 0.1))
    c.drawString(50, y, f'KONTOAUSZUG Nr. {random.randint(1, 52)} / 2026')
    y -= 20
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f'IBAN: DE89 6605 0101 {random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(10, 99)}')
    y -= 14
    c.drawString(50, y, f'BIC: KARSDE66XXX')
    y -= 14
    c.drawString(50, y, f'Kontoinhaber: Mycelium Enterprises UG')
    y -= 30

    # Umsaetze
    header = ['Datum', 'Buchungstext', 'Betrag']
    rows = [header]
    saldo = round(random.uniform(2000, 15000), 2)
    for _ in range(random.randint(5, 12)):
        d = _rand_date(30)
        text = random.choice([
            'SEPA-Ueberweisung an Finanzamt KA',
            'Gutschrift SEPA Amazon Payments',
            'Lastschrift Telekom',
            'Dauerauftrag Miete Waldstr. 42',
            'Kartenzahlung REWE',
            'Gutschrift Paypal',
            'SEPA-Lastschrift IONOS',
            'Gutschrift Brevo SAS',
        ])
        betrag = round(random.uniform(-2500, 3000), 2)
        saldo += betrag
        vorzeichen = '+' if betrag >= 0 else ''
        rows.append([d, text, f'{vorzeichen}{betrag:,.2f} EUR'])

    t = Table(rows, colWidths=[70, 300, 100])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.88, 0.88, 0.88)),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.Color(0.75, 0.75, 0.75)),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    tw, th = t.wrap(0, 0)
    t.drawOn(c, 50, y - th)
    y = y - th - 20

    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(W - 50, y, f'Neuer Saldo: {_eur(saldo)}')

    c.showPage()


def draw_versicherung(c: canvas.Canvas, idx: int):
    """Versicherungsschreiben / Police."""
    firma = random.choice([FIRMEN[2], FIRMEN[13]])  # Allianz oder HUK
    _gray_bg(c)
    _scan_noise(c)

    y = H - 60
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(colors.Color(0.0, 0.2, 0.5))
    c.drawString(50, y, firma[0])
    y -= 18
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(50, y, firma[1])
    y -= 60

    c.setFont('Helvetica-Bold', 14)
    c.setFillColor(colors.Color(0.1, 0.1, 0.1))
    typ = random.choice(['Beitragsrechnung', 'Versicherungsschein', 'Schadensmeldung Bestaetigung'])
    c.drawString(50, y, typ)
    y -= 24

    vnr = f'VN-{random.randint(100000, 999999)}'
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f'Vertragsnummer: {vnr}')
    c.drawString(350, y, f'Datum: {_rand_date()}')
    y -= 16
    sparte = random.choice(['Betriebshaftpflicht', 'Rechtsschutz', 'Elektronik', 'Cyber-Risk', 'Inhaltsversicherung'])
    c.drawString(50, y, f'Sparte: {sparte}')
    y -= 30

    if 'Beitragsrechnung' in typ:
        betrag = round(random.uniform(80, 1200), 2)
        c.setFont('Helvetica-Bold', 12)
        c.drawString(50, y, f'Jaehrl. Beitrag: {_eur(betrag)}')
        y -= 16
        c.setFont('Helvetica', 10)
        c.drawString(50, y, f'Faellig zum: {_rand_date(30)}')
    else:
        c.setFont('Helvetica', 10)
        c.drawString(50, y, f'Versicherungssumme: {_eur(random.uniform(50000, 500000))}')
        y -= 16
        c.drawString(50, y, f'Laufzeit: 01.01.2026 - 31.12.2026')

    c.showPage()


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    output_dir = Path(__file__).parent.parent / 'data'
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / 'test_belege_waeschekorb.pdf'

    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle('FRYA Test-Belege Waeschekorb')
    c.setAuthor('FRYA Test-Generator')

    # 22 Belege mit Trennseiten
    belege = [
        # 8x Rechnungen
        (draw_rechnung, 0), (draw_rechnung, 1), (draw_rechnung, 3),
        (draw_rechnung, 6), (draw_rechnung, 7), (draw_rechnung, 8),
        (draw_rechnung, 11), (draw_rechnung, 19),
        # 2x Gutschriften
        (draw_gutschrift, 2), (draw_gutschrift, 10),
        # 4x Quittungen
        (draw_quittung, 4), (draw_quittung, 5), (draw_quittung, 20), (draw_quittung, 21),
        # 2x Mahnungen
        (draw_mahnung, 3), (draw_mahnung, 12),
        # 2x Briefe
        (draw_brief, 9), (draw_brief, 17),
        # 2x Kontoauszuege
        (draw_kontoauszug, 14), (draw_kontoauszug, 14),
        # 2x Versicherung
        (draw_versicherung, 2), (draw_versicherung, 13),
    ]

    random.seed(42)  # Reproduzierbar

    for i, (draw_fn, firma_idx) in enumerate(belege, 1):
        # Trennseite VOR jedem Beleg (ausser dem ersten)
        if i > 1:
            draw_paperless_separator(c, asn=i)
        draw_fn(c, firma_idx)
        print(f'  Beleg {i:2d}/{len(belege)}: {draw_fn.__name__}')

    c.save()
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f'\nFertig: {output_path} ({size_mb:.1f} MB, {len(belege)} Belege)')
    return str(output_path)


if __name__ == '__main__':
    main()
