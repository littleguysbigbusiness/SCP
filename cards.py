import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

CARD_WIDTH = 3.375 * inch
CARD_HEIGHT = 2.125 * inch
MARGIN = 0.5 * inch
GAP = 0.25 * inch
COLS = 2
ROWS = 4

CLEARANCE_COLORS = {
    "0": colors.HexColor("#5b6167"),
    "1": colors.HexColor("#3f7d43"),
    "2": colors.HexColor("#2f6fa8"),
    "3": colors.HexColor("#c9a13b"),
    "4": colors.HexColor("#b04437"),
    "5": colors.HexColor("#1a1a1a"),
}
DEFAULT_COLOR = colors.HexColor("#5b6167")


def _clearance_color(level):
    for char in str(level):
        if char.isdigit():
            return CLEARANCE_COLORS.get(char, DEFAULT_COLOR)
    return DEFAULT_COLOR


def _draw_card(c, x, y, staff):
    accent = _clearance_color(staff.get("Clearance Level", ""))

    c.setFillColor(colors.HexColor("#14161a"))
    c.roundRect(x, y, CARD_WIDTH, CARD_HEIGHT, 6, fill=1, stroke=0)

    c.setFillColor(accent)
    c.rect(x, y + CARD_HEIGHT - 0.28 * inch, CARD_WIDTH, 0.28 * inch, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + 0.12 * inch, y + CARD_HEIGHT - 0.2 * inch, "SCP FOUNDATION")
    c.setFont("Helvetica", 6)
    c.drawRightString(x + CARD_WIDTH - 0.12 * inch, y + CARD_HEIGHT - 0.2 * inch, "SECURE. CONTAIN. PROTECT.")

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x + 0.14 * inch, y + CARD_HEIGHT - 0.55 * inch, str(staff.get("Name", ""))[:26])

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#c7cad0"))
    c.drawString(x + 0.14 * inch, y + CARD_HEIGHT - 0.72 * inch, str(staff.get("Role", ""))[:34])
    c.drawString(x + 0.14 * inch, y + CARD_HEIGHT - 0.86 * inch, str(staff.get("Site", ""))[:34])

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(accent)
    c.drawString(x + 0.14 * inch, y + 0.32 * inch, "CLEARANCE: {}".format(staff.get("Clearance Level", "N/A")))

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#8b9096"))
    c.drawString(
        x + 0.14 * inch,
        y + 0.16 * inch,
        "ID: {}   STATUS: {}".format(staff.get("ID", ""), staff.get("Status", "")),
    )

    c.setStrokeColor(accent)
    c.setLineWidth(1)
    c.roundRect(x, y, CARD_WIDTH, CARD_HEIGHT, 6, fill=0, stroke=1)


def build_keycards_pdf(staff_list):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    _, page_h = letter

    per_page = COLS * ROWS
    for i, staff in enumerate(staff_list):
        pos = i % per_page
        if i > 0 and pos == 0:
            c.showPage()
        col = pos % COLS
        row = pos // COLS
        x = MARGIN + col * (CARD_WIDTH + GAP)
        y = page_h - MARGIN - CARD_HEIGHT - row * (CARD_HEIGHT + GAP)
        _draw_card(c, x, y, staff)

    c.save()
    buf.seek(0)
    return buf
