#!/usr/bin/env python3
"""
FRYA Test-PDF Generator - Erzeugt 40 realistische Test-PDFs
fuer das Belegerkennungssystem.
"""

import os
import textwrap
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Table, TableStyle

BASE_DIR = r"C:\Users\lenovo\Documents\FRYA-Testbelege"

SUBDIRS = [
    "01_Eingangsrechnungen",
    "02_Tankbelege",
    "03_Quittungen",
    "04_Versicherungen",
    "05_Miete",
    "06_Steuerberater",
    "07_Ausgangsrechnungen",
    "08_Bescheide",
    "09_Fehlerfaelle",
]

# --- Mycelium Enterprises data (Absender fuer Ausgangsrechnungen) ---
MYCELIUM = {
    "name": "Mycelium Enterprises UG",
    "street": "Teststr. 1",
    "city": "76593 Gernsbach",
    "vat_id": "DE123456789",
    "iban": "DE89 1234 5678 9012 3456 78",
    "bic": "TESTDEFF",
    "bank": "Testbank AG",
}


def create_dirs():
    for sub in SUBDIRS:
        path = os.path.join(BASE_DIR, sub)
        os.makedirs(path, exist_ok=True)
    print(f"Verzeichnisse erstellt unter: {BASE_DIR}")


# ============================================================
# PDF HELPER FUNCTIONS
# ============================================================

def draw_header(c, sender_name, sender_street, sender_city, sender_extra=None):
    """Draw a standard invoice header."""
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, sender_name)
    c.setFont("Helvetica", 9)
    c.drawString(50, height - 65, sender_street)
    c.drawString(50, height - 77, sender_city)
    if sender_extra:
        c.drawString(50, height - 89, sender_extra)
    # Trennlinie
    c.setStrokeColor(HexColor("#333333"))
    c.setLineWidth(0.5)
    y_line = height - 100 if sender_extra else height - 92
    c.line(50, y_line, width - 50, y_line)
    return y_line


def draw_recipient(c, y, recipient_name, recipient_street, recipient_city):
    """Draw recipient block."""
    c.setFont("Helvetica", 10)
    c.drawString(50, y - 20, "An:")
    c.setFont("Helvetica", 11)
    c.drawString(50, y - 35, recipient_name)
    c.setFont("Helvetica", 10)
    c.drawString(50, y - 48, recipient_street)
    c.drawString(50, y - 61, recipient_city)
    return y - 75


def draw_invoice_meta(c, y, invoice_number, invoice_date, due_date=None):
    """Draw invoice metadata on the right side."""
    width, _ = A4
    x_right = width - 200
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_right, y - 20, f"Rechnungsnr.: {invoice_number}")
    c.setFont("Helvetica", 10)
    c.drawString(x_right, y - 35, f"Datum: {invoice_date}")
    if due_date:
        c.drawString(x_right, y - 50, f"Faellig: {due_date}")
    return y - 65


def draw_positions_table(c, y, positions, tax_rate=19):
    """Draw line items table. positions = list of (desc, qty, unit_price)"""
    width, _ = A4
    data = [["Pos.", "Beschreibung", "Menge", "Einzelpreis", "Gesamt"]]
    subtotal = 0
    for i, (desc, qty, price) in enumerate(positions, 1):
        total = qty * price
        subtotal += total
        data.append([
            str(i),
            desc,
            str(qty),
            f"{price:,.2f} EUR",
            f"{total:,.2f} EUR",
        ])

    tax_amount = subtotal * tax_rate / 100
    gross = subtotal + tax_amount

    data.append(["", "", "", "Netto:", f"{subtotal:,.2f} EUR"])
    data.append(["", "", "", f"MwSt ({tax_rate}%):", f"{tax_amount:,.2f} EUR"])
    data.append(["", "", "", "Brutto:", f"{gross:,.2f} EUR"])

    col_widths = [30, 220, 50, 80, 80]
    table = Table(data, colWidths=col_widths)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#4472C4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, len(positions)), 0.5, HexColor("#CCCCCC")),
        ("FONTNAME", (3, -3), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (3, -3), (-1, -3), 1, black),
        ("LINEABOVE", (3, -1), (-1, -1), 1.5, black),
    ])
    table.setStyle(style)
    tw, th = table.wrap(width - 100, 400)
    table.drawOn(c, 50, y - th - 10)
    return y - th - 20, gross


def draw_payment_info(c, y, iban, bic=None, bank=None):
    """Draw payment information."""
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y - 15, "Bankverbindung:")
    c.setFont("Helvetica", 9)
    c.drawString(50, y - 30, f"IBAN: {iban}")
    if bic:
        c.drawString(50, y - 43, f"BIC: {bic}")
    if bank:
        c.drawString(50, y - 56, f"Bank: {bank}")
    return y - 70


def draw_footer(c, text="Vielen Dank fuer Ihren Auftrag!"):
    """Draw footer text."""
    width, _ = A4
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(width / 2, 40, text)


# ============================================================
# INVOICE GENERATORS
# ============================================================

def create_invoice_pdf(filepath, sender, recipient, invoice_nr, date_str,
                       due_date, positions, tax_rate=19, extra_text=None,
                       payment_info=None):
    """Create a full invoice PDF."""
    c = canvas.Canvas(filepath, pagesize=A4)
    sender_extra = sender.get("extra")
    y = draw_header(c, sender["name"], sender["street"], sender["city"], sender_extra)
    y = draw_recipient(c, y, recipient["name"], recipient["street"], recipient["city"])
    y = draw_invoice_meta(c, y, invoice_nr, date_str, due_date)

    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, y - 15, "RECHNUNG")
    y = y - 25

    y, gross = draw_positions_table(c, y, positions, tax_rate)

    if payment_info:
        y = draw_payment_info(c, y, payment_info.get("iban", ""),
                              payment_info.get("bic"), payment_info.get("bank"))

    if extra_text:
        c.setFont("Helvetica", 9)
        for i, line in enumerate(extra_text.split("\n")):
            c.drawString(50, y - 15 - i * 13, line)

    draw_footer(c)
    c.save()
    print(f"  [OK] {os.path.basename(filepath)}")


def create_receipt_pdf(filepath, store_name, address, items, date_str,
                       receipt_nr=None, tax_rate=19):
    """Create a receipt/Kassenbon-style PDF."""
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # Smaller receipt style
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 50, store_name)
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, height - 65, address)
    c.drawCentredString(width / 2, height - 78, f"Datum: {date_str}")
    if receipt_nr:
        c.drawCentredString(width / 2, height - 91, f"Beleg-Nr.: {receipt_nr}")

    c.line(50, height - 100, width - 50, height - 100)

    y = height - 120
    total = 0
    c.setFont("Helvetica", 10)
    for desc, price in items:
        c.drawString(60, y, desc)
        c.drawRightString(width - 60, y, f"{price:,.2f} EUR")
        total += price
        y -= 15

    c.line(50, y - 5, width - 50, y - 5)
    y -= 20

    tax = total * tax_rate / (100 + tax_rate)  # MwSt already included
    netto = total - tax
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, y, "SUMME:")
    c.drawRightString(width - 60, y, f"{total:,.2f} EUR")
    y -= 15
    c.setFont("Helvetica", 9)
    c.drawString(60, y, f"darin enth. MwSt ({tax_rate}%):")
    c.drawRightString(width - 60, y, f"{tax:,.2f} EUR")

    draw_footer(c, "Kassenbon - bitte aufbewahren")
    c.save()
    print(f"  [OK] {os.path.basename(filepath)}")


def create_reminder_pdf(filepath, sender, recipient, invoice_nr, original_date,
                        original_amount, reminder_nr, reminder_date, due_date,
                        fee=0):
    """Create a payment reminder (Mahnung) PDF."""
    c = canvas.Canvas(filepath, pagesize=A4)
    y = draw_header(c, sender["name"], sender["street"], sender["city"],
                    sender.get("extra"))
    y = draw_recipient(c, y, recipient["name"], recipient["street"], recipient["city"])

    width, _ = A4
    x_right = width - 200
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_right, y - 20, f"Mahnung Nr.: {reminder_nr}")
    c.setFont("Helvetica", 10)
    c.drawString(x_right, y - 35, f"Datum: {reminder_date}")
    y = y - 50

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y - 10, f"ZAHLUNGSERINNERUNG")
    y -= 30

    c.setFont("Helvetica", 10)
    lines = [
        f"Leider konnten wir fuer folgende Rechnung noch keinen Zahlungseingang feststellen:",
        "",
        f"Rechnungsnummer: {invoice_nr}",
        f"Rechnungsdatum: {original_date}",
        f"Rechnungsbetrag: {original_amount:,.2f} EUR",
    ]
    if fee > 0:
        lines.append(f"Mahngebuehr: {fee:,.2f} EUR")
        lines.append(f"Gesamtbetrag: {original_amount + fee:,.2f} EUR")

    lines.extend([
        "",
        f"Bitte ueberweisen Sie den Betrag bis zum {due_date}.",
        "",
        "Mit freundlichen Gruessen",
        sender["name"],
    ])

    for line in lines:
        c.drawString(50, y, line)
        y -= 15

    draw_footer(c, "Bei bereits erfolgter Zahlung betrachten Sie dieses Schreiben als gegenstandslos.")
    c.save()
    print(f"  [OK] {os.path.basename(filepath)}")


def create_simple_doc_pdf(filepath, title, body_lines, footer_text=None):
    """Create a simple text-based PDF document (for Bescheide, Versicherungen, etc.)."""
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, title)
    c.line(50, height - 60, width - 50, height - 60)

    y = height - 85
    c.setFont("Helvetica", 10)
    for line in body_lines:
        if line.startswith("**"):
            c.setFont("Helvetica-Bold", 10)
            line = line.strip("*")
        else:
            c.setFont("Helvetica", 10)
        # Wrap long lines
        if len(line) > 90:
            wrapped = textwrap.wrap(line, width=90)
            for wl in wrapped:
                c.drawString(50, y, wl)
                y -= 14
        else:
            c.drawString(50, y, line)
            y -= 14

        if y < 60:
            c.showPage()
            y = height - 50

    if footer_text:
        draw_footer(c, footer_text)
    c.save()
    print(f"  [OK] {os.path.basename(filepath)}")


# ============================================================
# GENERATE ALL 40 PDFs
# ============================================================

def generate_all():
    create_dirs()

    # --------------------------------------------------------
    # 01_Eingangsrechnungen (10 PDFs: ER-001 bis ER-010)
    # --------------------------------------------------------
    print("\n=== 01_Eingangsrechnungen ===")
    folder = os.path.join(BASE_DIR, "01_Eingangsrechnungen")

    # ER-001 Buero-Discount Druckerpatronen
    create_invoice_pdf(
        os.path.join(folder, "ER-001_BueroDiscount_Druckerpatronen.pdf"),
        sender={"name": "Buero-Discount GmbH", "street": "Industriestr. 5", "city": "76137 Karlsruhe", "extra": "USt-IdNr.: DE987654321"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="BD-2026-1847",
        date_str="15.01.2026",
        due_date="14.02.2026",
        positions=[("HP 305XL Druckerpatrone schwarz", 2, 29.99), ("HP 305XL Druckerpatrone farbig", 1, 34.99)],
        tax_rate=19,
        payment_info={"iban": "DE12 3456 7890 1234 5678 90", "bic": "COBADEFFXXX", "bank": "Commerzbank Karlsruhe"},
    )

    # ER-002 Telekom Mobilfunk
    create_invoice_pdf(
        os.path.join(folder, "ER-002_Telekom_Mobilfunk.pdf"),
        sender={"name": "Deutsche Telekom AG", "street": "Friedrich-Ebert-Allee 140", "city": "53113 Bonn", "extra": "USt-IdNr.: DE123456789"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="T-2026-0001-4782",
        date_str="01.02.2026",
        due_date="15.02.2026",
        positions=[("Mobilfunk Business M", 1, 39.95), ("Daten-Flat 10GB", 1, 9.95)],
        tax_rate=19,
        payment_info={"iban": "DE85 5001 0517 5407 3249 31"},
    )

    # ER-003 IONOS Webhosting
    create_invoice_pdf(
        os.path.join(folder, "ER-003_IONOS_Webhosting.pdf"),
        sender={"name": "IONOS SE", "street": "Elgendorfer Str. 57", "city": "56410 Montabaur", "extra": "USt-IdNr.: DE815563912"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="ION-8834721",
        date_str="01.01.2026",
        due_date="15.01.2026",
        positions=[("Business Webhosting Plus (12 Monate)", 1, 9.00), ("SSL-Zertifikat Wildcard", 1, 4.00)],
        tax_rate=19,
        payment_info={"iban": "DE27 1001 0010 0987 6543 21"},
    )

    # ER-004 Amazon Business Bueroartikel
    create_invoice_pdf(
        os.path.join(folder, "ER-004_Amazon_Bueroartikel.pdf"),
        sender={"name": "Amazon EU S.a.r.l.", "street": "5 Rue Plaetis", "city": "L-2338 Luxemburg", "extra": "USt-IdNr.: LU26375245"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="INV-DE-2026-3847561",
        date_str="20.01.2026",
        due_date="03.02.2026",
        positions=[
            ("Ordner Leitz A4 breit, 10er Pack", 2, 24.90),
            ("Kopierpapier Navigator 500 Blatt", 5, 6.49),
            ("Heftklammern 24/6, 10.000 Stk", 1, 3.99),
        ],
        tax_rate=19,
    )

    # ER-005 Canva Pro Abo
    create_invoice_pdf(
        os.path.join(folder, "ER-005_Canva_Pro.pdf"),
        sender={"name": "Canva Pty Ltd", "street": "110 Kippax St", "city": "Surry Hills NSW 2010, Australia"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="CAN-EU-2026-992871",
        date_str="01.03.2026",
        due_date="01.03.2026",
        positions=[("Canva Pro Jahresabo (1 User)", 1, 109.99)],
        tax_rate=19,
        extra_text="Reverse-Charge: Steuerschuldnerschaft des Leistungsempfaengers (Art. 196 MwStSystRL)",
    )

    # ER-006 Deutsche Post Briefmarken
    create_invoice_pdf(
        os.path.join(folder, "ER-006_DeutschePost_Briefmarken.pdf"),
        sender={"name": "Deutsche Post AG", "street": "Charles-de-Gaulle-Str. 20", "city": "53113 Bonn", "extra": "USt-IdNr.: DE169838187"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="DP-2026-FF-771234",
        date_str="10.02.2026",
        due_date="24.02.2026",
        positions=[("Briefmarken Standardbrief 0,85 EUR, 100er Rolle", 1, 85.00)],
        tax_rate=19,
    )

    # ER-007 Zoom Video
    create_invoice_pdf(
        os.path.join(folder, "ER-007_Zoom_Business.pdf"),
        sender={"name": "Zoom Video Communications Inc.", "street": "55 Almaden Blvd", "city": "San Jose, CA 95113, USA"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="ZM-INV-2026-DE-48291",
        date_str="01.01.2026",
        due_date="01.01.2026",
        positions=[("Zoom Business (monthly)", 1, 18.99)],
        tax_rate=19,
        extra_text="Reverse-Charge: Steuerschuldnerschaft des Leistungsempfaengers",
    )

    # ER-008 Staples Buerobedarf
    create_invoice_pdf(
        os.path.join(folder, "ER-008_Staples_Buerobedarf.pdf"),
        sender={"name": "Staples Deutschland GmbH", "street": "Postfach 10 01 13", "city": "21677 Stade", "extra": "USt-IdNr.: DE813803768"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="STA-2026-9983742",
        date_str="05.03.2026",
        due_date="04.04.2026",
        positions=[
            ("Toner Samsung CLT-K504S schwarz", 1, 59.90),
            ("Schreibtischlampe LED dimmbar", 1, 34.99),
        ],
        tax_rate=19,
        payment_info={"iban": "DE44 2004 0000 0634 5678 00", "bic": "COBADEFFXXX"},
    )

    # ER-009 Vodafone DSL
    create_invoice_pdf(
        os.path.join(folder, "ER-009_Vodafone_DSL.pdf"),
        sender={"name": "Vodafone GmbH", "street": "Ferdinand-Braun-Platz 1", "city": "40549 Duesseldorf", "extra": "USt-IdNr.: DE812945tried"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="VF-2026-BW-3321987",
        date_str="01.03.2026",
        due_date="15.03.2026",
        positions=[("Red Internet & Phone 100 Cable", 1, 39.99)],
        tax_rate=19,
        payment_info={"iban": "DE72 3002 0900 6578 1234 56"},
    )

    # ER-010 DHL Paketversand
    create_invoice_pdf(
        os.path.join(folder, "ER-010_DHL_Paketversand.pdf"),
        sender={"name": "DHL Paket GmbH", "street": "Schildhornstr. 9", "city": "53113 Bonn", "extra": "USt-IdNr.: DE813563424"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="DHL-2026-GKDE-883271",
        date_str="28.02.2026",
        due_date="14.03.2026",
        positions=[
            ("Paket national bis 5kg", 10, 5.49),
            ("Paket national bis 10kg", 3, 7.49),
        ],
        tax_rate=19,
        payment_info={"iban": "DE86 3702 0500 0000 3006 00"},
    )

    # --------------------------------------------------------
    # 02_Tankbelege (3 PDFs: TB-001, TB-002, TB-003=Duplikat)
    # --------------------------------------------------------
    print("\n=== 02_Tankbelege ===")
    folder = os.path.join(BASE_DIR, "02_Tankbelege")

    create_receipt_pdf(
        os.path.join(folder, "TB-001_Aral_Tankbeleg.pdf"),
        store_name="Aral Tankstelle Gernsbach",
        address="Hauptstr. 42, 76593 Gernsbach",
        items=[("Super E10 42,5L x 1,789 EUR/L", 76.03)],
        date_str="12.02.2026 08:45",
        receipt_nr="TB-001-2026",
        tax_rate=19,
    )

    create_receipt_pdf(
        os.path.join(folder, "TB-002_Shell_Tankbeleg.pdf"),
        store_name="Shell Station Baden-Baden",
        address="Rheinstr. 100, 76532 Baden-Baden",
        items=[("Diesel 38,2L x 1,659 EUR/L", 63.37), ("Scheibenwaschmittel 5L", 8.99)],
        date_str="20.02.2026 14:22",
        receipt_nr="TB-002-2026",
        tax_rate=19,
    )

    # TB-003 = Duplikat von TB-001
    create_receipt_pdf(
        os.path.join(folder, "TB-003_Aral_Tankbeleg_DUPLIKAT.pdf"),
        store_name="Aral Tankstelle Gernsbach",
        address="Hauptstr. 42, 76593 Gernsbach",
        items=[("Super E10 42,5L x 1,789 EUR/L", 76.03)],
        date_str="12.02.2026 08:45",
        receipt_nr="TB-001-2026",
        tax_rate=19,
    )

    # --------------------------------------------------------
    # 03_Quittungen (3 PDFs)
    # --------------------------------------------------------
    print("\n=== 03_Quittungen ===")
    folder = os.path.join(BASE_DIR, "03_Quittungen")

    create_receipt_pdf(
        os.path.join(folder, "QU-001_Schreibwarenladen.pdf"),
        store_name="Schreibwaren Mueller",
        address="Marktplatz 3, 76593 Gernsbach",
        items=[("Druckerpapier A4 500Bl", 4.99), ("Kugelschreiber 10er", 3.49), ("Briefumschlaege C5 50St", 5.99)],
        date_str="05.01.2026 10:12",
        receipt_nr="QU-2026-0001",
        tax_rate=19,
    )

    create_receipt_pdf(
        os.path.join(folder, "QU-002_Baumarkt.pdf"),
        store_name="OBI Markt Gaggenau",
        address="Industriestr. 20, 76571 Gaggenau",
        items=[("Verlängerungskabel 5m", 12.99), ("LED-Gluehbirne E27 3er Pack", 9.99)],
        date_str="18.01.2026 16:30",
        receipt_nr="QU-2026-0002",
        tax_rate=19,
    )

    create_receipt_pdf(
        os.path.join(folder, "QU-003_Postfiliale.pdf"),
        store_name="Deutsche Post Filiale Gernsbach",
        address="Hauptstr. 15, 76593 Gernsbach",
        items=[("Paket national 5kg", 5.49), ("Einschreiben Einwurf", 2.35)],
        date_str="22.02.2026 11:05",
        receipt_nr="QU-2026-0003",
        tax_rate=19,
    )

    # --------------------------------------------------------
    # 04_Versicherungen (2 PDFs)
    # --------------------------------------------------------
    print("\n=== 04_Versicherungen ===")
    folder = os.path.join(BASE_DIR, "04_Versicherungen")

    create_simple_doc_pdf(
        os.path.join(folder, "VS-001_Betriebshaftpflicht.pdf"),
        title="Allianz Versicherungs-AG",
        body_lines=[
            "Koelner Landstr. 346, 40627 Duesseldorf",
            "",
            "**Versicherungsschein Nr. BH-2026-7781234**",
            "",
            f"Versicherungsnehmer: {MYCELIUM['name']}",
            f"Anschrift: {MYCELIUM['street']}, {MYCELIUM['city']}",
            "",
            "**Betriebshaftpflichtversicherung**",
            "",
            "Versicherungszeitraum: 01.01.2026 - 31.12.2026",
            "Deckungssumme: 3.000.000,00 EUR (Personen-/Sachschaeden)",
            "Deckungssumme: 100.000,00 EUR (Vermoegensschaeden)",
            "",
            "Jahresbeitrag: 487,50 EUR (inkl. Versicherungssteuer 19%)",
            "Zahlungsweise: jaehrlich",
            "Faellig am: 01.01.2026",
            "",
            "Ihr Beitrag wird am 05.01.2026 per SEPA-Lastschrift eingezogen.",
            "",
            "IBAN: DE89 1234 5678 9012 3456 78",
            "Mandatsreferenz: ALZ-BH-2026-7781234",
        ],
        footer_text="Allianz Versicherungs-AG - Sitz: Muenchen - HRB 164232",
    )

    create_simple_doc_pdf(
        os.path.join(folder, "VS-002_Rechtsschutz.pdf"),
        title="ARAG SE",
        body_lines=[
            "ARAG Platz 1, 40472 Duesseldorf",
            "",
            "**Beitragsrechnung Nr. RS-2026-442189**",
            "",
            f"Versicherungsnehmer: {MYCELIUM['name']}",
            f"Anschrift: {MYCELIUM['street']}, {MYCELIUM['city']}",
            "",
            "**Firmen-Rechtsschutzversicherung**",
            "",
            "Versicherungszeitraum: 01.01.2026 - 31.12.2026",
            "Selbstbeteiligung: 250,00 EUR",
            "",
            "Jahresbeitrag: 345,00 EUR (inkl. Versicherungssteuer 19%)",
            "Zahlungsweise: jaehrlich",
            "Faellig am: 15.01.2026",
            "",
            "Bitte ueberweisen Sie den Betrag auf:",
            "IBAN: DE55 3005 0110 1007 8901 23",
            "BIC: DUSSDEDDXXX",
            "Verwendungszweck: RS-2026-442189",
        ],
        footer_text="ARAG SE - Sitz: Duesseldorf - HRB 66846",
    )

    # --------------------------------------------------------
    # 05_Miete (1 PDF)
    # --------------------------------------------------------
    print("\n=== 05_Miete ===")
    folder = os.path.join(BASE_DIR, "05_Miete")

    create_simple_doc_pdf(
        os.path.join(folder, "MI-001_Buero_Miete_Maerz.pdf"),
        title="Immobilien Schmitt GmbH",
        body_lines=[
            "Schlossstr. 12, 76593 Gernsbach",
            "USt-IdNr.: DE298765432",
            "",
            "**Mietrechnung Maerz 2026**",
            "",
            f"Mieter: {MYCELIUM['name']}",
            f"Objekt: Buero EG links, Teststr. 1, 76593 Gernsbach",
            "",
            "Zeitraum: 01.03.2026 - 31.03.2026",
            "",
            "Kaltmiete:                     450,00 EUR",
            "Nebenkosten-Vorauszahlung:     120,00 EUR",
            "Gesamt netto:                  570,00 EUR",
            "MwSt. (19%):                   108,30 EUR",
            "Gesamt brutto:                 678,30 EUR",
            "",
            "Bitte ueberweisen Sie bis zum 03.03.2026 auf:",
            "IBAN: DE67 6605 0101 0012 3456 78",
            "Verwendungszweck: Miete Maerz 2026 / Teststr. 1 EG",
        ],
        footer_text="Immobilien Schmitt GmbH - Amtsgericht Mannheim HRB 54321",
    )

    # --------------------------------------------------------
    # 06_Steuerberater (1 PDF)
    # --------------------------------------------------------
    print("\n=== 06_Steuerberater ===")
    folder = os.path.join(BASE_DIR, "06_Steuerberater")

    create_invoice_pdf(
        os.path.join(folder, "STB-001_Steuerberater_Quartal.pdf"),
        sender={"name": "Steuerberatung Dr. Fischer", "street": "Am Marktplatz 7", "city": "76530 Baden-Baden", "extra": "USt-IdNr.: DE334455667"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="STB-2026-Q1-0047",
        date_str="15.03.2026",
        due_date="14.04.2026",
        positions=[
            ("Finanzbuchhaltung Q1/2026", 1, 450.00),
            ("USt-Voranmeldung Jan-Maerz 2026", 3, 75.00),
            ("Lohnabrechnung Jan-Maerz (1 MA)", 3, 35.00),
        ],
        tax_rate=19,
        payment_info={"iban": "DE34 6605 0101 0087 6543 21", "bic": "KARSDE66XXX", "bank": "Sparkasse Baden-Baden"},
    )

    # --------------------------------------------------------
    # 07_Ausgangsrechnungen (13 PDFs: AR-001 bis AR-013)
    # --------------------------------------------------------
    print("\n=== 07_Ausgangsrechnungen ===")
    folder = os.path.join(BASE_DIR, "07_Ausgangsrechnungen")

    mycelium_sender = {
        "name": MYCELIUM["name"],
        "street": MYCELIUM["street"],
        "city": MYCELIUM["city"],
        "extra": f"USt-IdNr.: {MYCELIUM['vat_id']}",
    }
    mycelium_payment = {
        "iban": MYCELIUM["iban"],
        "bic": MYCELIUM["bic"],
        "bank": MYCELIUM["bank"],
    }

    # AR-001
    create_invoice_pdf(
        os.path.join(folder, "AR-001_Coaching_Mueller.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Anna Mueller", "street": "Blumenweg 4", "city": "76593 Gernsbach"},
        invoice_nr="RE-2026-001",
        date_str="10.01.2026",
        due_date="09.02.2026",
        positions=[("Einzelcoaching-Session 90min", 3, 120.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-002
    create_invoice_pdf(
        os.path.join(folder, "AR-002_Workshop_Schmidt.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Brigitte Schmidt", "street": "Waldstr. 22", "city": "76532 Baden-Baden"},
        invoice_nr="RE-2026-002",
        date_str="15.01.2026",
        due_date="14.02.2026",
        positions=[("Tagesworkshop 'Innere Staerke'", 1, 350.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-003
    create_invoice_pdf(
        os.path.join(folder, "AR-003_GruppenCoaching_Weber.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Markus Weber", "street": "Ringstr. 8", "city": "76571 Gaggenau"},
        invoice_nr="RE-2026-003",
        date_str="20.01.2026",
        due_date="19.02.2026",
        positions=[("Gruppen-Coaching 4 Personen, 3 Stunden", 1, 480.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-004
    create_invoice_pdf(
        os.path.join(folder, "AR-004_Coaching_Hoffmann.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Petra Hoffmann", "street": "Lindenstr. 15", "city": "76534 Baden-Baden"},
        invoice_nr="RE-2026-004",
        date_str="25.01.2026",
        due_date="24.02.2026",
        positions=[("Coaching-Session 90min", 4, 120.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-005
    create_invoice_pdf(
        os.path.join(folder, "AR-005_Retreat_Berger.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Klaus Berger", "street": "Bergstr. 3", "city": "76530 Baden-Baden"},
        invoice_nr="RE-2026-005",
        date_str="01.02.2026",
        due_date="01.03.2026",
        positions=[("Retreat Wochenende (2 Tage inkl. Material)", 1, 890.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-006
    create_invoice_pdf(
        os.path.join(folder, "AR-006_OnlineCoaching_Maier.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Sabine Maier", "street": "Gartenweg 7", "city": "76547 Sinzheim"},
        invoice_nr="RE-2026-006",
        date_str="05.02.2026",
        due_date="07.03.2026",
        positions=[("Online-Coaching 90min", 3, 90.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-007
    create_invoice_pdf(
        os.path.join(folder, "AR-007_Erstgespraech_Richter.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Thomas Richter", "street": "Sonnenstr. 11", "city": "76571 Gaggenau"},
        invoice_nr="RE-2026-007",
        date_str="10.02.2026",
        due_date="12.03.2026",
        positions=[("Erstgespraech 90min", 1, 150.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-008
    create_invoice_pdf(
        os.path.join(folder, "AR-008_Seminar_VHS.pdf"),
        sender=mycelium_sender,
        recipient={"name": "VHS Baden-Baden", "street": "Briegelackerstr. 8", "city": "76532 Baden-Baden"},
        invoice_nr="RE-2026-008",
        date_str="15.02.2026",
        due_date="17.03.2026",
        positions=[("Seminar 'Potenzial-Entfaltung' (Tagesseminar)", 1, 600.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-009
    create_invoice_pdf(
        os.path.join(folder, "AR-009_Vortrag_Unternehmerverband.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Unternehmerverband BW e.V.", "street": "Kriegsstr. 125", "city": "76135 Karlsruhe"},
        invoice_nr="RE-2026-009",
        date_str="20.02.2026",
        due_date="22.03.2026",
        positions=[("Vortrag Keynote 'Resiliente Fuehrung'", 1, 450.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-010
    create_invoice_pdf(
        os.path.join(folder, "AR-010_Onlinekurs_Digistore.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Digistore24 GmbH", "street": "St.-Godehard-Str. 32", "city": "31139 Hildesheim"},
        invoice_nr="RE-2026-010",
        date_str="01.03.2026",
        due_date="31.03.2026",
        positions=[("Onlinekurs 'Schattenarbeit' Lizenz (Quartal)", 1, 380.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-011
    create_invoice_pdf(
        os.path.join(folder, "AR-011_KursAbo_Elopage.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Elopage GmbH", "street": "Kurfuerstendamm 182", "city": "10707 Berlin"},
        invoice_nr="RE-2026-011",
        date_str="01.03.2026",
        due_date="31.03.2026",
        positions=[("Kurs-Abo Lizenzgebuehr (Monat)", 1, 165.00)],
        tax_rate=19,
        payment_info=mycelium_payment,
    )

    # AR-012 (7% MwSt - Buch)
    create_invoice_pdf(
        os.path.join(folder, "AR-012_Buchverkauf_Fischer.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Buchhandlung Fischer", "street": "Lessingstr. 5", "city": "76530 Baden-Baden"},
        invoice_nr="RE-2026-012",
        date_str="10.03.2026",
        due_date="09.04.2026",
        positions=[("Buch 'Wege zum Selbst' (Autorenexemplare)", 20, 18.90)],
        tax_rate=7,
        payment_info=mycelium_payment,
        extra_text="Ermaessigter Steuersatz gemaess par. 12 Abs. 2 Nr. 1 UStG (Buecher)",
    )

    # AR-013 (7% MwSt - eBook)
    create_invoice_pdf(
        os.path.join(folder, "AR-013_eBook_Lizenz_Thalia.pdf"),
        sender=mycelium_sender,
        recipient={"name": "Thalia Bucher GmbH", "street": "Bahnhofstr. 1-5", "city": "58095 Hagen"},
        invoice_nr="RE-2026-013",
        date_str="15.03.2026",
        due_date="14.04.2026",
        positions=[("eBook 'Innere Ruhe finden' - Digitallizenz", 1, 250.00)],
        tax_rate=7,
        payment_info=mycelium_payment,
        extra_text="Ermaessigter Steuersatz gemaess par. 12 Abs. 2 Nr. 14 UStG (eBooks)",
    )

    # --------------------------------------------------------
    # 08_Bescheide (2 PDFs)
    # --------------------------------------------------------
    print("\n=== 08_Bescheide ===")
    folder = os.path.join(BASE_DIR, "08_Bescheide")

    create_simple_doc_pdf(
        os.path.join(folder, "BE-001_USt_Vorauszahlung_Q4.pdf"),
        title="Finanzamt Baden-Baden",
        body_lines=[
            "Rettigstr. 1, 76530 Baden-Baden",
            "",
            "**Bescheid ueber die Umsatzsteuer-Vorauszahlung**",
            "**Oktober - Dezember 2025**",
            "",
            f"Steuerpflichtiger: {MYCELIUM['name']}",
            f"Steuernummer: 218/5741/0815",
            f"Anschrift: {MYCELIUM['street']}, {MYCELIUM['city']}",
            "",
            "Umsatzsteuer Q4/2025:",
            "Steuerbare Umsaetze (19%):         12.450,00 EUR",
            "Umsatzsteuer darauf:                 2.365,50 EUR",
            "Steuerbare Umsaetze (7%):              756,00 EUR",
            "Umsatzsteuer darauf:                    52,92 EUR",
            "Vorsteuer:                           -1.234,12 EUR",
            "",
            "**Vorauszahlung: 1.184,30 EUR**",
            "",
            "Faellig am: 10.02.2026",
            "Bankverbindung: Bundeskasse Trier",
            "IBAN: DE81 5900 0000 0059 0010 20",
            "Verwendungszweck: 218/5741/0815 USt Q4/2025",
        ],
        footer_text="Dieser Bescheid ist maschinell erstellt und ohne Unterschrift gueltig.",
    )

    create_simple_doc_pdf(
        os.path.join(folder, "BE-002_GewSt_Vorauszahlung.pdf"),
        title="Stadt Gernsbach - Kaemmerei",
        body_lines=[
            "Igelbachstr. 11, 76593 Gernsbach",
            "",
            "**Bescheid ueber die Gewerbesteuer-Vorauszahlung 2026**",
            "",
            f"Steuerpflichtiger: {MYCELIUM['name']}",
            f"Anschrift: {MYCELIUM['street']}, {MYCELIUM['city']}",
            "Aktenzeichen: GewSt-2026-0815",
            "",
            "Festgesetzter Steuermessbetrag: 245,00 EUR",
            "Hebesatz Stadt Gernsbach: 380%",
            "",
            "**Gewerbesteuer-Vorauszahlung Q1/2026: 931,00 EUR**",
            "",
            "Faellig am: 15.02.2026",
            "",
            "Bitte ueberweisen Sie auf:",
            "Sparkasse Rastatt-Gernsbach",
            "IBAN: DE55 6655 0070 0000 1234 56",
            "Verwendungszweck: GewSt-2026-0815 Q1",
        ],
        footer_text="Stadt Gernsbach - Dieser Bescheid ist maschinell erstellt.",
    )

    # --------------------------------------------------------
    # 09_Fehlerfaelle (4 PDFs)
    # --------------------------------------------------------
    print("\n=== 09_Fehlerfaelle ===")
    folder = os.path.join(BASE_DIR, "09_Fehlerfaelle")

    # FF-001: Phantomfirma (nicht existente Firma)
    create_invoice_pdf(
        os.path.join(folder, "FF-001_Phantomfirma_Rechnung.pdf"),
        sender={"name": "XYZ Phantom Services Ltd.", "street": "Fake Street 999", "city": "00000 Nirgendwo"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="PHANTOM-0001",
        date_str="01.03.2026",
        due_date="15.03.2026",
        positions=[("Consulting Services Premium", 1, 4999.00)],
        tax_rate=19,
        extra_text="ACHTUNG: Keine USt-IdNr. angegeben!\nKein Impressum vorhanden.",
    )

    # FF-002: Rechnung ohne MwSt-Ausweis
    create_invoice_pdf(
        os.path.join(folder, "FF-002_Ohne_MwSt_Ausweis.pdf"),
        sender={"name": "Freelancer Hans Nosteuer", "street": "Steuerfreiweg 1", "city": "76593 Gernsbach"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="FN-2026-001",
        date_str="15.02.2026",
        due_date="17.03.2026",
        positions=[("Webdesign Landingpage", 1, 800.00)],
        tax_rate=0,
        extra_text="Hinweis: Kein Ausweis von Umsatzsteuer (Kleinunternehmerregelung par. 19 UStG)\nKeine USt-IdNr. vorhanden - Vorsteuerabzug NICHT moeglich.",
    )

    # FF-003: Mahnung ohne zugehoerige Rechnung
    create_reminder_pdf(
        os.path.join(folder, "FF-003_Mahnung_ohne_Rechnung.pdf"),
        sender={"name": "Unbekannt GmbH", "street": "Musterstr. 99", "city": "12345 Musterstadt"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="UNBEKANNT-9999",
        original_date="01.12.2025",
        original_amount=1250.00,
        reminder_nr="M-2026-001",
        reminder_date="01.03.2026",
        due_date="15.03.2026",
        fee=5.00,
    )

    # FF-004: Rechnung mit Zukunftsdatum
    create_invoice_pdf(
        os.path.join(folder, "FF-004_Zukunftsdatum_Rechnung.pdf"),
        sender={"name": "Zeitreise Consulting AG", "street": "Zukunftsallee 42", "city": "80331 Muenchen", "extra": "USt-IdNr.: DE111222333"},
        recipient={"name": MYCELIUM["name"], "street": MYCELIUM["street"], "city": MYCELIUM["city"]},
        invoice_nr="ZK-2027-001",
        date_str="15.06.2027",
        due_date="15.07.2027",
        positions=[("Strategieberatung Future Planning", 1, 2500.00)],
        tax_rate=19,
        extra_text="WARNUNG: Rechnungsdatum liegt in der Zukunft!",
    )

    # --------------------------------------------------------
    # README.txt
    # --------------------------------------------------------
    print("\n=== README.txt ===")
    readme_path = os.path.join(BASE_DIR, "README.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("""FRYA Testbelege - Uebersicht
=============================
Erstellt am: {date}
Anzahl Belege: 40 (inkl. 1 Duplikat)

Ordnerstruktur:
  01_Eingangsrechnungen/  (10 PDFs: ER-001 bis ER-010)
  02_Tankbelege/          (3 PDFs: TB-001, TB-002, TB-003=Duplikat von TB-001)
  03_Quittungen/          (3 PDFs: QU-001 bis QU-003)
  04_Versicherungen/      (2 PDFs: VS-001, VS-002)
  05_Miete/               (1 PDF: MI-001)
  06_Steuerberater/       (1 PDF: STB-001)
  07_Ausgangsrechnungen/  (13 PDFs: AR-001 bis AR-013, AR-012/013 mit 7% MwSt)
  08_Bescheide/           (2 PDFs: BE-001, BE-002)
  09_Fehlerfaelle/        (4 PDFs: FF-001 Phantomfirma, FF-002 ohne MwSt,
                           FF-003 Mahnung ohne Rechnung, FF-004 Zukunftsdatum)

Absender Ausgangsrechnungen:
  Mycelium Enterprises UG
  Teststr. 1, 76593 Gernsbach
  USt-IdNr.: DE123456789
  IBAN: DE89 1234 5678 9012 3456 78

Spezialfaelle:
  - TB-003 ist ein exaktes Duplikat von TB-001 (Duplikaterkennung testen)
  - AR-012 und AR-013 verwenden 7% MwSt (ermaessigter Satz fuer Buecher/eBooks)
  - FF-001: Phantomfirma ohne USt-IdNr
  - FF-002: Kleinunternehmer ohne MwSt-Ausweis (kein Vorsteuerabzug)
  - FF-003: Mahnung zu nicht-existierender Rechnung
  - FF-004: Rechnung mit Datum in der Zukunft (2027)
""".format(date=datetime.now().strftime("%Y-%m-%d %H:%M")))
    print("  [OK] README.txt")


def count_pdfs():
    """Count all generated PDFs."""
    total = 0
    for sub in SUBDIRS:
        path = os.path.join(BASE_DIR, sub)
        if os.path.exists(path):
            pdfs = [f for f in os.listdir(path) if f.endswith(".pdf")]
            total += len(pdfs)
            print(f"  {sub}: {len(pdfs)} PDFs")
    print(f"\n  GESAMT: {total} PDFs")
    return total


if __name__ == "__main__":
    print("=" * 60)
    print("FRYA Test-PDF Generator")
    print("=" * 60)
    generate_all()
    print("\n" + "=" * 60)
    print("ZUSAMMENFASSUNG:")
    print("=" * 60)
    count_pdfs()
    print(f"\nAlle Dateien unter: {BASE_DIR}")
    print("FERTIG!")
