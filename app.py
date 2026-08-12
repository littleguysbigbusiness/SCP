import os
from datetime import datetime, timezone

from flask import Flask, redirect, render_template, request, send_file, url_for

import cards
import sheets_client as sc

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

TILES = [
    {"key": "archives", "title": "Archives", "description": "SCP object records and containment data."},
    {"key": "staff", "title": "Staff", "description": "Personnel roster and clearance levels."},
    {"key": "communications", "title": "Communications", "description": "Internal message and incident log."},
]

PRINT_TILES = [
    {
        "key": "keycards",
        "title": "Keycards",
        "description": "Bulk-generate staff keycards as a printable PDF.",
        "ready": True,
    },
    {
        "key": "staff_ids",
        "title": "Staff IDs",
        "description": "Bulk-generate staff ID badges as a printable PDF.",
        "ready": True,
    },
    {
        "key": "stickers",
        "title": "Stickers",
        "description": "Awaiting sticker template.",
        "ready": False,
    },
]


@app.route("/")
def dashboard():
    counts = {}
    for tile in TILES:
        try:
            counts[tile["key"]] = len(sc.get_rows(tile["key"]))
        except Exception:
            counts[tile["key"]] = None
    return render_template("dashboard.html", tiles=TILES, counts=counts)


def _list_view(key, title):
    config = sc.TABS[key]

    if request.method == "POST":
        row = {h: request.form.get(h, "").strip() for h in config["headers"]}
        if key == "communications" and not row.get("Timestamp"):
            row["Timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sc.add_row(key, row)
        return redirect(url_for(key))

    error = None
    rows = []
    try:
        rows = sc.get_rows(key)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "list.html", title=title, headers=config["headers"], rows=rows, key=key, error=error
    )


@app.route("/archives", methods=["GET", "POST"])
def archives():
    return _list_view("archives", "Archives")


@app.route("/staff", methods=["GET", "POST"])
def staff():
    return _list_view("staff", "Staff")


@app.route("/communications", methods=["GET", "POST"])
def communications():
    return _list_view("communications", "Communications")


@app.route("/print")
def print_hub():
    return render_template("print_hub.html", tiles=PRINT_TILES)


def _selected_staff_rows():
    staff_rows = sc.get_rows("staff")
    selected = request.form.getlist("selected")
    if not selected:
        return staff_rows
    indices = {int(i) for i in selected if i.isdigit()}
    return [row for idx, row in enumerate(staff_rows) if idx in indices]


def _print_select_view(page_title, post_endpoint):
    error = None
    staff_rows = []
    try:
        staff_rows = sc.get_rows("staff")
    except Exception as exc:
        error = str(exc)
    return render_template(
        "print_staff_select.html",
        page_title=page_title,
        post_url=url_for(post_endpoint),
        staff_rows=staff_rows,
        error=error,
    )


@app.route("/print/keycards")
def print_keycards():
    return _print_select_view("Keycards", "print_keycards_pdf")


@app.route("/print/keycards/pdf", methods=["POST"])
def print_keycards_pdf():
    chosen = _selected_staff_rows()
    if not chosen:
        return redirect(url_for("print_keycards"))

    pdf_buf = cards.build_keycards_pdf(chosen)
    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="scp_keycards.pdf",
    )


@app.route("/print/staff-ids")
def print_staff_ids():
    return _print_select_view("Staff IDs", "print_staff_ids_pdf")


@app.route("/print/staff-ids/pdf", methods=["POST"])
def print_staff_ids_pdf():
    chosen = _selected_staff_rows()
    if not chosen:
        return redirect(url_for("print_staff_ids"))

    pdf_buf = cards.build_staff_id_pdf(chosen)
    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="scp_staff_ids.pdf",
    )


@app.route("/print/stickers")
def print_stickers():
    return render_template("print_placeholder.html", title="Stickers")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
