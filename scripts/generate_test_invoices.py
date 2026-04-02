"""Generate 8 realistic test invoices as PDF for FRYA P-09 testing."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(__file__), '..', 'test_belege')
os.makedirs(OUT, exist_ok=True)

W, H = A4

def _header(c, sender_lines, recipient_lines, doc_title, doc_nr, doc_date):
    y = H - 40*mm
    c.setFont('Helvetica-Bold', 9)
    for line in sender_lines:
        c.drawString(25*mm, y, line)
        y -= 4.5*mm
    y -= 6*mm
    c.setFont('Helvetica', 9)
    for line in recipient_lines:
        c.drawString(25*mm, y, line)
        y -= 4.5*mm
    y -= 10*mm
    c.setFont('Helvetica-Bold', 14)
    c.drawString(25*mm, y, doc_title)
    y -= 8*mm
    c.setFont('Helvetica', 9)
    c.drawString(25*mm, y, f'Rechnungsnr.: {doc_nr}')
    c.drawString(120*mm, y, f'Datum: {doc_date}')
    y -= 6*mm
    return y

def _table(c, y, rows, col_widths=None):
    """rows: list of tuples. First row is header."""
    x0 = 25*mm
    if not col_widths:
        col_widths = [70*mm, 20*mm, 25*mm, 25*mm, 25*mm]
    for i, row in enumerate(rows):
        x = x0
        font = 'Helvetica-Bold' if i == 0 else 'Helvetica'
        c.setFont(font, 8)
        for j, cell in enumerate(row):
            w = col_widths[j] if j < len(col_widths) else 25*mm
            c.drawString(x + 1*mm, y, str(cell))
            x += w
        y -= 5*mm
        if i == 0:
            c.line(x0, y + 1*mm, x0 + sum(col_widths[:len(row)]), y + 1*mm)
            y -= 2*mm
    return y

def _totals(c, y, lines):
    x = 120*mm
    for label, val, bold in lines:
        font = 'Helvetica-Bold' if bold else 'Helvetica'
        c.setFont(font, 9)
        c.drawString(x, y, label)
        c.drawRightString(170*mm, y, val)
        y -= 5*mm
    return y

def _footer(c, text):
    c.setFont('Helvetica', 7)
    c.drawString(25*mm, 20*mm, text)

# ── Beleg 1: Telekom ─────────────────────────────────────────
def beleg1():
    p = os.path.join(OUT, 'beleg1_telekom.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Deutsche Telekom AG', 'Landgrabenweg 151', '53227 Bonn'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Rechnung', '2026-TEL-44281', '15.03.2026')
    y = _table(c, y, [
        ('Beschreibung', 'Menge', 'Netto', 'MwSt', 'Brutto'),
        ('Mobilfunk Business L, Maerz 2026', '1', '39,99 EUR', '19%', '47,59 EUR'),
    ])
    y -= 8*mm
    y = _totals(c, y, [
        ('Netto:', '39,99 EUR', False),
        ('MwSt 19%:', '7,60 EUR', False),
        ('Gesamt:', '47,59 EUR', True),
    ])
    _footer(c, 'Deutsche Telekom AG · Landgrabenweg 151 · 53227 Bonn · USt-IdNr: DE123456789')
    c.save()
    print(f'  {p}')

# ── Beleg 2: Bueromiete ──────────────────────────────────────
def beleg2():
    p = os.path.join(OUT, 'beleg2_bueromiete.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Immobilien Schneider GmbH', 'Kaiserstr. 45', '76530 Baden-Baden'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Rechnung', 'MV-2026-03', '01.03.2026')
    y = _table(c, y, [
        ('Beschreibung', 'Menge', 'Netto', 'MwSt', 'Brutto'),
        ('Bueromiete Maerz 2026, Kaiserstr. 45, EG links', '1', '450,00 EUR', '19%', '535,50 EUR'),
    ])
    y -= 8*mm
    y = _totals(c, y, [
        ('Netto:', '450,00 EUR', False),
        ('MwSt 19%:', '85,50 EUR', False),
        ('Gesamt:', '535,50 EUR', True),
    ])
    c.setFont('Helvetica', 8)
    c.drawString(25*mm, y - 8*mm, 'Zahlbar innerhalb von 14 Tagen auf IBAN DE89 3704 0044 0532 0130 00')
    _footer(c, 'Immobilien Schneider GmbH · Kaiserstr. 45 · 76530 Baden-Baden')
    c.save()
    print(f'  {p}')

# ── Beleg 3: Tankbeleg ───────────────────────────────────────
def beleg3():
    p = os.path.join(OUT, 'beleg3_tankbeleg.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = H - 40*mm
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(W/2, y, 'ARAL Station')
    y -= 6*mm
    c.setFont('Helvetica', 9)
    c.drawCentredString(W/2, y, 'Hauptstr. 12, 76593 Gernsbach')
    y -= 10*mm
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(W/2, y, 'Kassenbon')
    y -= 6*mm
    c.setFont('Helvetica', 9)
    c.drawString(25*mm, y, 'Beleg-Nr: 4471')
    c.drawRightString(W - 25*mm, y, '20.03.2026')
    y -= 10*mm
    c.drawString(25*mm, y, 'Super E10, 32,5 Liter')
    c.drawRightString(W - 25*mm, y, '52,65 EUR')
    y -= 8*mm
    c.line(25*mm, y, W - 25*mm, y)
    y -= 6*mm
    c.setFont('Helvetica-Bold', 10)
    c.drawString(25*mm, y, 'SUMME')
    c.drawRightString(W - 25*mm, y, '52,65 EUR')
    y -= 6*mm
    c.setFont('Helvetica', 8)
    c.drawString(25*mm, y, 'davon MwSt 19%: 8,41 EUR')
    _footer(c, 'Aral AG · USt-IdNr: DE811164801')
    c.save()
    print(f'  {p}')

# ── Beleg 4: AWS ─────────────────────────────────────────────
def beleg4():
    p = os.path.join(OUT, 'beleg4_aws.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Amazon Web Services EMEA SARL', '38 Avenue John F. Kennedy', 'L-1855 Luxembourg'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Invoice', 'INV-EU-2026-1847291', '01.04.2026')
    y = _table(c, y, [
        ('Description', 'Qty', 'Net', 'Tax', 'Total'),
        ('Amazon EC2 (eu-central-1), March 2026', '1', '18,42 EUR', '0%', '18,42 EUR'),
        ('Amazon S3 Storage, March 2026', '1', '3,21 EUR', '0%', '3,21 EUR'),
        ('Amazon CloudWatch, March 2026', '1', '1,87 EUR', '0%', '1,87 EUR'),
    ])
    y -= 8*mm
    y = _totals(c, y, [
        ('Netto:', '23,50 EUR', False),
        ('MwSt:', '0,00 EUR', False),
        ('Gesamt:', '23,50 EUR', True),
    ])
    c.setFont('Helvetica-Oblique', 8)
    c.drawString(25*mm, y - 8*mm, 'Steuerschuldnerschaft des Leistungsempfaengers gemaess §13b UStG (Reverse Charge)')
    _footer(c, 'Amazon Web Services EMEA SARL · 38 Avenue JFK · L-1855 Luxembourg · VAT: LU26375245')
    c.save()
    print(f'  {p}')

# ── Beleg 5: Restaurant ──────────────────────────────────────
def beleg5():
    p = os.path.join(OUT, 'beleg5_restaurant.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = H - 40*mm
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(W/2, y, 'Gasthaus Zum Hirsch')
    y -= 6*mm
    c.setFont('Helvetica', 9)
    c.drawCentredString(W/2, y, 'Marktplatz 3, 76530 Baden-Baden')
    y -= 10*mm
    c.setFont('Helvetica', 9)
    c.drawString(25*mm, y, 'Beleg-Nr: 887')
    c.drawRightString(W - 25*mm, y, '25.03.2026')
    y -= 10*mm
    items = [
        ('2x Schnitzel mit Pommes', '29,80 EUR'),
        ('2x Mineralwasser 0,5l', '7,00 EUR'),
    ]
    for desc, price in items:
        c.drawString(25*mm, y, desc)
        c.drawRightString(W - 25*mm, y, price)
        y -= 5*mm
    y -= 3*mm
    c.line(25*mm, y, W - 25*mm, y)
    y -= 6*mm
    c.setFont('Helvetica-Bold', 10)
    c.drawString(25*mm, y, 'SUMME')
    c.drawRightString(W - 25*mm, y, '36,80 EUR')
    y -= 6*mm
    c.setFont('Helvetica', 8)
    c.drawString(25*mm, y, 'davon MwSt 19%: 5,88 EUR')
    _footer(c, 'Gasthaus Zum Hirsch · Inh. Hans Mueller · Marktplatz 3 · 76530 Baden-Baden')
    c.save()
    print(f'  {p}')

# ── Beleg 6: Versicherung ────────────────────────────────────
def beleg6():
    p = os.path.join(OUT, 'beleg6_versicherung.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Allianz Versicherungs-AG', 'Koeniginstr. 28', '80802 Muenchen'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Beitragsrechnung', 'BHV-2024-887412', '01.01.2026')
    y = _table(c, y, [
        ('Beschreibung', 'Zeitraum', 'Betrag', '', ''),
        ('Betriebshaftpflichtversicherung 2026', '01.01.-31.12.2026', '342,00 EUR', '', ''),
    ], col_widths=[80*mm, 40*mm, 30*mm, 5*mm, 5*mm])
    y -= 8*mm
    y = _totals(c, y, [
        ('Gesamtbetrag:', '342,00 EUR', True),
    ])
    c.setFont('Helvetica', 8)
    c.drawString(25*mm, y - 8*mm, 'Versicherungssteuer bereits im Beitrag enthalten. Faellig: 15.01.2026')
    _footer(c, 'Allianz Versicherungs-AG · Koeniginstr. 28 · 80802 Muenchen')
    c.save()
    print(f'  {p}')

# ── Beleg 7: Software-Lizenz ─────────────────────────────────
def beleg7():
    p = os.path.join(OUT, 'beleg7_software.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Software Solutions GmbH', 'Friedrichstr. 100', '10117 Berlin'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Rechnung', 'SS-2026-0042', '28.03.2026')
    y = _table(c, y, [
        ('Beschreibung', 'Menge', 'Netto', 'MwSt', 'Brutto'),
        ('Jahreslizenz Business Suite', '1', '1.200,00 EUR', '19%', '1.428,00 EUR'),
    ])
    y -= 8*mm
    y = _totals(c, y, [
        ('Netto:', '1.200,00 EUR', False),
        ('MwSt 19%:', '228,00 EUR', False),
        ('Gesamt:', '1.428,00 EUR', True),
    ])
    c.setFont('Helvetica', 8)
    c.drawString(25*mm, y - 8*mm, 'Zahlbar innerhalb von 30 Tagen. IBAN: DE71 1001 0010 0123 4567 89')
    _footer(c, 'Software Solutions GmbH · Friedrichstr. 100 · 10117 Berlin · USt-IdNr: DE987654321')
    c.save()
    print(f'  {p}')

# ── Beleg 8: Gutschrift ──────────────────────────────────────
def beleg8():
    p = os.path.join(OUT, 'beleg8_gutschrift.pdf')
    c = canvas.Canvas(p, pagesize=A4)
    y = _header(c,
        ['Buero Discount GmbH', 'Industriestr. 7', '76185 Karlsruhe'],
        ['Mycelium Enterprises UG', 'Teststr. 1', '76593 Gernsbach'],
        'Gutschrift', 'GS-2026-0019', '22.03.2026')
    c.setFont('Helvetica', 9)
    c.drawString(25*mm, y, 'Bezug: Retoure zu Rechnung RD-2026-1847')
    y -= 8*mm
    y = _table(c, y, [
        ('Beschreibung', 'Menge', 'Netto', 'MwSt', 'Brutto'),
        ('Bueroklammern 1000er Pack', '3', '-4,99 EUR', '19%', '-5,94 EUR'),
    ])
    y -= 8*mm
    y = _totals(c, y, [
        ('Netto:', '-14,97 EUR', False),
        ('MwSt 19%:', '-2,84 EUR', False),
        ('Gutschrift:', '-17,81 EUR', True),
    ])
    _footer(c, 'Buero Discount GmbH · Industriestr. 7 · 76185 Karlsruhe')
    c.save()
    print(f'  {p}')

if __name__ == '__main__':
    print('Generating 8 test invoices...')
    beleg1()
    beleg2()
    beleg3()
    beleg4()
    beleg5()
    beleg6()
    beleg7()
    beleg8()
    print(f'Done. Files in {os.path.abspath(OUT)}')
