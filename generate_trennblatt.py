"""Generate FRYA Scanner Separator Sheet (Trennblatt) as A4 PDF."""
import io
import os
import barcode
from barcode.writer import SVGWriter
from fpdf import FPDF

OUTPUT_PATH = os.path.expanduser(r'~\Desktop\FRYA-Trennblatt.pdf')
FRYA_ORANGE = (232, 120, 48)  # #E87830


class TrennblattPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=False)


def generate():
    pdf = TrennblattPDF()
    pdf.add_page()
    w, h = 210, 297  # A4 mm

    # ── Background: subtle light orange border ──────────────────────────────
    pdf.set_draw_color(*FRYA_ORANGE)
    pdf.set_line_width(1.5)
    pdf.rect(10, 10, w - 20, h - 20)

    # ── Top accent bar ─────────────────────────────────────────────────────
    pdf.set_fill_color(*FRYA_ORANGE)
    pdf.rect(10, 10, w - 20, 8, 'F')

    # ── FRYA Logo text ─────────────────────────────────────────────────────
    pdf.set_y(30)
    pdf.set_font('Helvetica', 'B', 52)
    pdf.set_text_color(*FRYA_ORANGE)
    pdf.cell(w, 20, 'FRYA', align='C', new_x='LMARGIN', new_y='NEXT')

    # ── Subtitle ───────────────────────────────────────────────────────────
    pdf.set_y(55)
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(w, 8, 'Dein intelligenter Buchhalter', align='C', new_x='LMARGIN', new_y='NEXT')

    # ── Thin separator line ────────────────────────────────────────────────
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(40, 72, w - 40, 72)

    # ── Main title ─────────────────────────────────────────────────────────
    pdf.set_y(82)
    pdf.set_font('Helvetica', 'B', 22)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(w, 12, 'Trennblatt', align='C', new_x='LMARGIN', new_y='NEXT')

    # ── Instruction text ───────────────────────────────────────────────────
    pdf.set_y(100)
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(w, 10, 'Zwischen deine Belege legen', align='C', new_x='LMARGIN', new_y='NEXT')

    # ── Generate CODE 39 barcode as SVG → PNG via fpdf ─────────────────────
    code39 = barcode.get('code39', 'PATCHT', writer=SVGWriter())
    svg_buffer = io.BytesIO()
    code39.write(svg_buffer, options={
        'module_width': 0.6,
        'module_height': 25,
        'write_text': True,
        'font_size': 14,
        'text_distance': 5,
        'quiet_zone': 6,
    })
    svg_data = svg_buffer.getvalue()

    # Save SVG temporarily, embed as image
    svg_path = os.path.join(os.path.dirname(OUTPUT_PATH), '_frya_barcode.svg')
    with open(svg_path, 'wb') as f:
        f.write(svg_data)

    # Place barcode centered
    barcode_w = 80  # mm width
    barcode_h = 35  # mm height
    barcode_x = (w - barcode_w) / 2
    barcode_y = 125
    pdf.image(svg_path, x=barcode_x, y=barcode_y, w=barcode_w, h=barcode_h)

    # ── Explanatory text below barcode ─────────────────────────────────────
    pdf.set_y(170)
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(w, 8, 'Paperless erkennt dieses Blatt automatisch', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(w, 6, 'und trennt deine Dokumente.', align='C', new_x='LMARGIN', new_y='NEXT')

    # ── Bottom icon-style hints ────────────────────────────────────────────
    pdf.set_y(200)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(150, 150, 150)

    hints = [
        'Dieses Blatt vor jeden neuen Beleg legen',
        'Der Scanner erkennt den Barcode und startet ein neues Dokument',
        'Beliebig oft ausdrucken und wiederverwenden',
    ]
    for hint in hints:
        pdf.set_x(40)
        # Orange bullet
        pdf.set_fill_color(*FRYA_ORANGE)
        pdf.ellipse(42, pdf.get_y() + 2.5, 3, 3, 'F')
        pdf.set_x(50)
        pdf.cell(w - 80, 8, hint, new_x='LMARGIN', new_y='NEXT')

    # ── Bottom accent bar ──────────────────────────────────────────────────
    pdf.set_fill_color(*FRYA_ORANGE)
    pdf.rect(10, h - 18, w - 20, 8, 'F')

    # ── Footer text ────────────────────────────────────────────────────────
    pdf.set_y(h - 28)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(w, 5, 'myfrya.de', align='C')

    # ── Save ───────────────────────────────────────────────────────────────
    pdf.output(OUTPUT_PATH)
    print(f'Trennblatt gespeichert: {OUTPUT_PATH}')

    # Cleanup temp barcode
    try:
        os.remove(svg_path)
    except OSError:
        pass


if __name__ == '__main__':
    generate()
