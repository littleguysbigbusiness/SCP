import copy
import io
import os
import random
import urllib.request

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.code128 import Code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

PHOTO_FETCH_TIMEOUT = 5
PHOTO_MAX_BYTES = 5 * 1024 * 1024

LOGO_SVG_PATH = os.path.join(os.path.dirname(__file__), "static", "assets", "scp_logo.svg")

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

# Muted palette used on the Staff ID badge (unrelated to the keycard palette below).
CLEARANCE_COLORS = {
    "0": colors.HexColor("#5b6167"),
    "1": colors.HexColor("#3f7d43"),
    "2": colors.HexColor("#2f6fa8"),
    "3": colors.HexColor("#c9a13b"),
    "4": colors.HexColor("#b04437"),
    "5": colors.HexColor("#5a4a7a"),
}
DEFAULT_COLOR = colors.HexColor("#5b6167")

# Matches the classic SCP wiki keycard set: numbered levels get a light/bright
# band with black text, anything else (O5, blank, unrecognized) falls back to
# the dark blue "undesignated" card with white text.
KEYCARD_LEVEL_COLORS = {
    "0": colors.HexColor("#a8a6a2"),
    "1": colors.HexColor("#f5df15"),
    "2": colors.HexColor("#f0b91a"),
    "3": colors.HexColor("#f2953a"),
    "4": colors.HexColor("#e8541e"),
    "5": colors.HexColor("#dd1f2d"),
}
KEYCARD_DEFAULT_COLOR = colors.HexColor("#26348a")


def _clearance_color(level):
    for char in str(level):
        if char.isdigit():
            return CLEARANCE_COLORS.get(char, DEFAULT_COLOR)
    return DEFAULT_COLOR


def _keycard_level_label(clearance):
    text = str(clearance or "").strip()
    if not text:
        return None
    if "o5" in text.lower():
        return "O5"
    for char in text:
        if char.isdigit():
            return char
    return None


def _keycard_style(clearance):
    label = _keycard_level_label(clearance)
    color = KEYCARD_LEVEL_COLORS.get(label, KEYCARD_DEFAULT_COLOR)
    return label, color


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

    c.setFillColor(colors.HexColor("#5b6167"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + width / 2, y + height / 2 - 0.03 * inch, "N/A")


def _make_barcode(value, target_width, height):
    bc = Code128(str(value) or "N/A", barHeight=height, barWidth=0.6)
    if bc.width > 0:
        bc.barWidth *= target_width / bc.width
        bc = Code128(str(value) or "N/A", barHeight=height, barWidth=bc.barWidth)
    return bc


def _draw_qr(c, x, y, size, value):
    qr = QrCodeWidget(str(value) or "N/A")
    x0, y0, x1, y1 = qr.getBounds()
    w, h = x1 - x0, y1 - y0
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, -x0 * size / w, -y0 * size / h])
    d.add(qr)
    renderPDF.draw(d, c, x, y)


_logo_drawing_cache = None


def _get_logo_drawing():
    global _logo_drawing_cache
    if _logo_drawing_cache is None:
        _logo_drawing_cache = svg2rlg(LOGO_SVG_PATH)
    return _logo_drawing_cache


def _recolor(node, color):
    if getattr(node, "strokeColor", None) is not None:
        node.strokeColor = color
    if getattr(node, "fillColor", None) is not None:
        node.fillColor = color
    for child in getattr(node, "contents", []) or []:
        _recolor(child, color)


def _draw_logo(c, x, y, size, color=colors.black):
    d = copy.deepcopy(_get_logo_drawing())
    _recolor(d, color)
    scale = size / max(d.width, d.height)
    d.width *= scale
    d.height *= scale
    d.scale(scale, scale)
    renderPDF.draw(d, c, x, y)


def _draw_triangle(c, x, y, half_height, color):
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x, y + half_height)
    p.lineTo(x, y - half_height)
    p.lineTo(x + half_height * 1.15, y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


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
    # Layout modeled on the classic SCP wiki keycard set: colored top band
    # (wordmark + emblem + tagline + QR + arrow), white "LEVEL n" band with
    # the standard warning text, solid color footer. Numbered clearance
    # levels get a light band with black text; anything else (O5, blank,
    # unrecognized) falls back to the dark blue card with white text.
    label, band_color = _keycard_style(staff.get("Clearance Level"))
    text_color = colors.white if label is None else colors.black

    top_h = 0.86 * inch
    mid_h = 0.94 * inch
    bot_h = CARD_HEIGHT - top_h - mid_h
    pad = 0.1 * inch

    top_y0 = y + CARD_HEIGHT - top_h
    mid_y0 = top_y0 - mid_h

    c.setFillColor(colors.white)
    c.rect(x, y, CARD_WIDTH, CARD_HEIGHT, fill=1, stroke=0)

    # Top band
    c.setFillColor(band_color)
    c.rect(x, top_y0, CARD_WIDTH, top_h, fill=1, stroke=0)

    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(x + pad, y + CARD_HEIGHT - 0.30 * inch, "SCP")
    scp_w = c.stringWidth("SCP", "Helvetica-Bold", 19)
    _draw_logo(c, x + pad + scp_w + 0.08 * inch, y + CARD_HEIGHT - 0.36 * inch, 0.26 * inch, color=text_color)

    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(x + pad, top_y0 + 0.11 * inch, "Secure. Contain. Protect.")

    qr_size = 0.48 * inch
    qr_x = x + CARD_WIDTH - 0.85 * inch
    qr_y = top_y0 + (top_h - qr_size) / 2
    c.setFillColor(colors.white)
    c.roundRect(qr_x - 0.04 * inch, qr_y - 0.04 * inch, qr_size + 0.08 * inch, qr_size + 0.08 * inch, 2, fill=1, stroke=0)
    _draw_qr(c, qr_x, qr_y, qr_size, "SCP-STAFF-{}".format(staff.get("ID", "N/A")))

    _draw_triangle(c, x + CARD_WIDTH - pad - 0.12 * inch, top_y0 + top_h / 2, 0.09 * inch, text_color)

    # Middle band
    c.setFillColor(colors.HexColor("#f4f3ef"))
    c.rect(x, mid_y0, CARD_WIDTH, mid_h, fill=1, stroke=0)

    content_top = top_y0 - 0.22 * inch
    if label:
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(x + pad, content_top, "LEVEL {}".format(label))

    disclaimer = [
        "Giving this key card to personell with",
        "an insufficient security clearance is",
        "strictly forbidden.",
    ]
    c.setFont("Helvetica-Bold", 5.8)
    c.setFillColor(colors.HexColor("#1a1a1a"))
    for i, line in enumerate(disclaimer):
        c.drawString(x + pad, content_top - 0.20 * inch - i * 0.10 * inch, line)

    staff_line = "{}  -  ID {}".format(staff.get("Name", "UNASSIGNED"), staff.get("ID", "N/A"))
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(colors.HexColor("#33383f"))
    c.drawString(x + pad, mid_y0 + 0.08 * inch, staff_line[:40])

    _draw_triangle(c, x + CARD_WIDTH - pad - 0.12 * inch, mid_y0 + mid_h / 2, 0.09 * inch, colors.black)

    # Bottom band
    c.setFillColor(band_color)
    c.rect(x, y, CARD_WIDTH, bot_h, fill=1, stroke=0)

    c.setStrokeColor(colors.HexColor("#c9c7c2"))
    c.setLineWidth(1)
    c.rect(x, y, CARD_WIDTH, CARD_HEIGHT, fill=0, stroke=1)


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
    _draw_logo(c, x + CARD_WIDTH - pad - 0.16 * inch, y + CARD_HEIGHT - header_h + 0.04 * inch, 0.16 * inch, color=colors.white)

    content_top = y + CARD_HEIGHT - header_h - 0.08 * inch

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#8b9096"))
    area = staff.get("Area") or _assign_area(staff.get("ID", ""))
    c.drawRightString(x + CARD_WIDTH - pad, content_top, "AREA: {}".format(area))

    photo_w = photo_h = 0.85 * inch
    photo_x = x + CARD_WIDTH - pad - photo_w
    photo_top = content_top - 0.14 * inch
    photo_y = photo_top - photo_h
    _draw_photo_box(c, photo_x, photo_y, photo_w, photo_h, staff.get("Photo URL"))

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#c7cad0"))
    c.drawRightString(x + CARD_WIDTH - pad, photo_y - 0.16 * inch, "AGE: {}".format(staff.get("Age") or "N/A"))
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

    fields = ["To", "From", "Mail Back To", "Address", "Notes"]
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

    logo_size = LOGO_SIZE * 0.58
    _draw_logo(c, cx - logo_size / 2, cy - logo_size / 2 + 0.08 * inch, logo_size, color=colors.HexColor("#14161a"))

    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(ACCENT)
    c.drawCentredString(cx, cy - logo_size / 2 - 0.02 * inch, "SCP FOUNDATION")


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
