import io
import random
import urllib.request

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PHOTO_FETCH_TIMEOUT = 5
PHOTO_MAX_BYTES = 5 * 1024 * 1024

AREA_POOL = [
    "Area 3",
    "Area 7",
    "Area 12",
    "Area 19",
    "Sector A",
    "Sector C",
    "Sector G",
    "Records Wing",
    "Containment Wing B",
    "Admin Block",
]

CARD_WIDTH = 3.375 * inch
CARD_HEIGHT = 2.125 * inch
MARGIN = 0.5 * inch
GAP = 0.25 * inch

TAG_WIDTH = 2.2 * inch
TAG_HEIGHT = 1.4 * inch
LOGO_SIZE = 1.4 * inch
STICKER_MARGIN = 0.5 * inch
STICKER_GAP = 0.2 * inch

ACCENT = colors.HexColor("#c9a13b")

CLEARANCE_COLORS = {
    "0": colors.HexColor("#5b6167"),
    "1": colors.HexColor("#3f7d43"),
    "2": colors.HexColor("#2f6fa8"),
    "3": colors.HexColor("#c9a13b"),
    "4": colors.HexColor("#b04437"),
    "5": colors.HexColor("#5a4a7a"),
}
DEFAULT_COLOR = colors.HexColor("#5b6167")


def _clearance_color(level):
    for char in str(level):
        if char.isdigit():
            return CLEARANCE_COLORS.get(char, DEFAULT_COLOR)
    return DEFAULT_COLOR


def _assign_area(staff_id):
    # No "area" column exists in the sheet - each staff member gets a
    # facility area assigned at print time, seeded by their ID so the same
    # person always gets the same area on reprints.
    seed = str(staff_id) or "unassigned"
    return random.Random(seed).choice(AREA_POOL)


def _fetch_photo(url):
    if not url or not str(url).lower().startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(url, timeout=PHOTO_FETCH_TIMEOUT) as resp:
            data = resp.read(PHOTO_MAX_BYTES + 1)
        if len(data) > PHOTO_MAX_BYTES:
            return None
        return ImageReader(io.BytesIO(data))
    except Exception:
        return None


def _draw_photo_box(c, x, y, width, height, photo_url):
    image = _fetch_photo(photo_url)
    if image is not None:
        try:
            c.saveState()
            p = c.beginPath()
            p.rect(x, y, width, height)
            c.clipPath(p, stroke=0, fill=0)
            c.drawImage(image, x, y, width=width, height=height, preserveAspectRatio=True, anchor="c")
            c.restoreState()
            return
        except Exception:
            pass

    c.setFillColor(colors.HexColor("#0d0e10"))
    c.rect(x, y, width, height, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#33383f"))
    c.setLineWidth(0.75)
    c.rect(x, y, width, height, fill=0, stroke=1)

    cx = x + width / 2
    c.setFillColor(colors.HexColor("#33383f"))
    c.circle(cx, y + height * 0.62, width * 0.2, fill=1, stroke=0)
    c.ellipse(x + width * 0.18, y + height * 0.08, x + width * 0.82, y + height * 0.5, fill=1, stroke=0)


def _make_barcode(value, target_width, height):
    bc = Code128(str(value) or "N/A", barHeight=height, barWidth=0.6)
    if bc.width > 0:
        bc.barWidth *= target_width / bc.width
        bc = Code128(str(value) or "N/A", barHeight=height, barWidth=bc.barWidth)
    return bc


def _draw_seal(c, cx, cy, r, color):
    c.setStrokeColor(color)
    c.setLineWidth(1)
    c.circle(cx, cy, r, fill=0, stroke=1)
    c.circle(cx, cy, r * 0.55, fill=0, stroke=1)
    c.setFillColor(color)
    c.circle(cx, cy, r * 0.15, fill=1, stroke=0)


def _tile_grid(item_w, item_h, page_w, page_h, margin, gap):
    cols = int((page_w - 2 * margin + gap) // (item_w + gap))
    rows = int((page_h - 2 * margin + gap) // (item_h + gap))
    return max(cols, 1), max(rows, 1)


def _build_grid_pdf(items, item_w, item_h, draw_fn, margin=MARGIN, gap=GAP):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    page_w, page_h = letter
    cols, rows = _tile_grid(item_w, item_h, page_w, page_h, margin, gap)
    per_page = cols * rows

    for i, item in enumerate(items):
        pos = i % per_page
        if i > 0 and pos == 0:
            c.showPage()
        col = pos % cols
        row = pos // cols
        x = margin + col * (item_w + gap)
        y = page_h - margin - item_h - row * (item_h + gap)
        draw_fn(c, x, y, item)

    c.save()
    buf.seek(0)
    return buf


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


def _draw_id_card(c, x, y, staff):
    accent = _clearance_color(staff.get("Clearance Level", ""))
    pad = 0.12 * inch
    header_h = 0.26 * inch

    c.setFillColor(colors.HexColor("#14161a"))
    c.roundRect(x, y, CARD_WIDTH, CARD_HEIGHT, 6, fill=1, stroke=0)

    c.setFillColor(accent)
    c.rect(x, y + CARD_HEIGHT - header_h, CARD_WIDTH, header_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + pad, y + CARD_HEIGHT - header_h + 0.07 * inch, "SCP FOUNDATION")
    _draw_seal(c, x + CARD_WIDTH - pad - 0.07 * inch, y + CARD_HEIGHT - header_h / 2, 0.09 * inch, colors.white)

    content_top = y + CARD_HEIGHT - header_h - 0.08 * inch

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#8b9096"))
    c.drawRightString(x + CARD_WIDTH - pad, content_top, "AREA: {}".format(_assign_area(staff.get("ID", ""))))

    photo_w = photo_h = 0.85 * inch
    photo_x = x + CARD_WIDTH - pad - photo_w
    photo_top = content_top - 0.14 * inch
    photo_y = photo_top - photo_h
    _draw_photo_box(c, photo_x, photo_y, photo_w, photo_h, staff.get("Photo URL"))

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#c7cad0"))
    c.drawRightString(x + CARD_WIDTH - pad, photo_y - 0.16 * inch, "AGE: {}".format(staff.get("Age", "N/A")))
    c.drawRightString(
        x + CARD_WIDTH - pad, photo_y - 0.30 * inch, "STAFF ID: {}".format(staff.get("ID", ""))
    )

    left_x = x + pad
    line_h = 0.185 * inch
    label_font_size = 7
    fields = [
        ("Name", staff.get("Name", "")),
        ("Role", staff.get("Role", "")),
        ("Access Level", staff.get("Clearance Level", "")),
        ("Role Rank", staff.get("Role Rank", "")),
        ("Born", staff.get("Born", "")),
    ]
    value_x = left_x + max(
        c.stringWidth("{}:".format(label), "Helvetica-Bold", label_font_size) for label, _ in fields
    ) + 0.08 * inch

    for i, (label, value) in enumerate(fields):
        row_y = content_top - i * line_h
        is_name = label == "Name"
        c.setFont("Helvetica-Bold", label_font_size)
        c.setFillColor(colors.HexColor("#c7cad0") if is_name else colors.HexColor("#8b9096"))
        c.drawString(left_x, row_y, "{}:".format(label))
        c.setFont("Helvetica-Bold" if is_name else "Helvetica", 7.5 if is_name else 7)
        c.setFillColor(colors.white)
        c.drawString(value_x, row_y, str(value)[:26])

    barcode_h = 0.28 * inch
    barcode_w = CARD_WIDTH - 2 * pad
    barcode = _make_barcode(staff.get("ID", "N/A"), barcode_w, barcode_h)
    c.setFillColor(colors.white)
    c.rect(x + pad, y + 0.06 * inch, barcode_w, barcode_h + 0.04 * inch, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    barcode.drawOn(c, x + pad, y + 0.08 * inch)

    c.setStrokeColor(accent)
    c.setLineWidth(1)
    c.roundRect(x, y, CARD_WIDTH, CARD_HEIGHT, 6, fill=0, stroke=1)


def _draw_envelope_tag(c, x, y):
    header_h = 0.22 * inch
    pad = 0.1 * inch

    c.setFillColor(colors.white)
    c.rect(x, y, TAG_WIDTH, TAG_HEIGHT, fill=1, stroke=0)

    c.setFillColor(ACCENT)
    c.rect(x, y + TAG_HEIGHT - header_h, TAG_WIDTH, header_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(x + TAG_WIDTH / 2, y + TAG_HEIGHT - header_h + 0.06 * inch, "SCP FOUNDATION")

    fields = ["To", "From", "Address", "Notes"]
    content_h = TAG_HEIGHT - header_h - pad
    line_h = content_h / len(fields)
    content_top = y + TAG_HEIGHT - header_h - 0.03 * inch

    for i, label in enumerate(fields):
        row_y = content_top - i * line_h - line_h * 0.68
        label_text = "{}:".format(label)
        c.setFont("Helvetica-Bold", 6)
        c.setFillColor(colors.HexColor("#33383f"))
        c.drawString(x + pad, row_y, label_text)

        label_w = c.stringWidth(label_text, "Helvetica-Bold", 6)
        c.setStrokeColor(colors.HexColor("#a9adb2"))
        c.setLineWidth(0.5)
        c.line(x + pad + label_w + 0.05 * inch, row_y - 0.02 * inch, x + TAG_WIDTH - pad, row_y - 0.02 * inch)

    c.setStrokeColor(ACCENT)
    c.setLineWidth(1)
    c.rect(x, y, TAG_WIDTH, TAG_HEIGHT, fill=0, stroke=1)


def _draw_logo_sticker(c, x, y):
    r = LOGO_SIZE / 2
    cx, cy = x + r, y + r

    c.setFillColor(colors.white)
    c.circle(cx, cy, r, fill=1, stroke=0)

    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.5)
    c.circle(cx, cy, r - 0.03 * inch, fill=0, stroke=1)
    c.setLineWidth(0.75)
    c.circle(cx, cy, r * 0.62, fill=0, stroke=1)

    c.setFillColor(colors.HexColor("#14161a"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(cx, cy + 0.02 * inch, "SCP")
    c.setFont("Helvetica", 5.5)
    c.setFillColor(ACCENT)
    c.drawCentredString(cx, cy - 0.17 * inch, "FOUNDATION")


def build_staff_id_pdf(staff_list):
    return _build_grid_pdf(staff_list, CARD_WIDTH, CARD_HEIGHT, lambda c, x, y, s: _draw_id_card(c, x, y, s))


def build_keycards_pdf(staff_list):
    return _build_grid_pdf(staff_list, CARD_WIDTH, CARD_HEIGHT, lambda c, x, y, s: _draw_card(c, x, y, s))


def build_envelope_tags_pdf(count):
    return _build_grid_pdf(
        range(count),
        TAG_WIDTH,
        TAG_HEIGHT,
        lambda c, x, y, _: _draw_envelope_tag(c, x, y),
        margin=STICKER_MARGIN,
        gap=STICKER_GAP,
    )


def build_logo_stickers_pdf(count):
    return _build_grid_pdf(
        range(count),
        LOGO_SIZE,
        LOGO_SIZE,
        lambda c, x, y, _: _draw_logo_sticker(c, x, y),
        margin=STICKER_MARGIN,
        gap=STICKER_GAP,
    )
