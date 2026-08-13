import os
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for

import auth
import cards
import drive_client
import ocr_client
import sheets_client as sc

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

OBJECT_CLASS_TAGS = {
    "safe": "safe",
    "euclid": "euclid",
    "keter": "keter",
    "thaumiel": "thaumiel",
    "apollyon": "keter",
    "neutralized": "neutral",
    "explained": "neutral",
}

# Same families as cards.py's CLEARANCE_COLORS/KEYCARD_LEVEL_COLORS, so a
# staff member's clearance tag on-screen matches their printed keycard.
CLEARANCE_LEVEL_TAGS = {"0": "neutral", "1": "safe", "2": "blue", "3": "euclid", "4": "keter", "5": "thaumiel"}


@app.template_filter("class_tag")
def class_tag(value):
    return OBJECT_CLASS_TAGS.get((value or "").strip().lower(), "neutral")


@app.template_filter("clearance_tag")
def clearance_tag(value):
    text = str(value or "")
    if "o5" in text.lower():
        return "o5"
    for char in text:
        if char.isdigit():
            return CLEARANCE_LEVEL_TAGS.get(char, "neutral")
    return "neutral"


@app.before_request
def _require_login():
    endpoint = request.endpoint
    if endpoint is None or endpoint in auth.OPEN_ENDPOINTS:
        return
    if "staff_name" not in session:
        return redirect(url_for("login"))
    if not session.get("privileged") and endpoint not in auth.UNPRIVILEGED_ENDPOINTS:
        return redirect(url_for("staff_duties"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "")
        password = request.form.get("password", "")
        if password != auth.LOGIN_PASSWORD:
            error = "Incorrect password."
        else:
            try:
                staff_row = auth.find_staff_by_name(name)
            except Exception as exc:
                staff_row = None
                error = "Unable to reach the database: {}".format(exc)
            if staff_row is None and error is None:
                error = "No staff member found with that name."
            if staff_row is not None:
                session.clear()
                session["staff_name"] = staff_row.get("Name")
                session["staff_id"] = staff_row.get("ID")
                session["staff_role"] = (staff_row.get("Role") or "").strip()
                session["privileged"] = auth.is_privileged(staff_row)
                return redirect(url_for("dashboard" if session["privileged"] else "staff_duties"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/staff-duties")
def staff_duties():
    return render_template("staff_duties.html")


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
        "description": "Print envelope tags and Foundation logo stickers.",
        "ready": True,
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


@app.route("/archives/scan", methods=["GET", "POST"])
def archives_scan():
    fields = [h for h in sc.TABS["archives"]["headers"] if h != "Scan URL"]

    if request.method == "POST":
        error = None
        scan_url = ""
        file = request.files.get("document")
        if file and file.filename:
            try:
                scan_url = drive_client.upload_scan(file)
            except Exception as exc:
                error = "Could not upload scan: {}".format(exc)

        if error:
            return render_template("archives_scan.html", fields=fields, error=error, form=request.form)

        row = {h: request.form.get(h, "").strip() for h in fields}
        if not row.get("Date Added"):
            row["Date Added"] = datetime.now(timezone.utc).date().isoformat()
        row["Scan URL"] = scan_url
        sc.add_row("archives", row)
        return redirect(url_for("archives"))

    return render_template("archives_scan.html", fields=fields, error=None, form={})


@app.route("/archives/scan/analyze", methods=["POST"])
def archives_scan_analyze():
    file = request.files.get("document")
    if not file or not file.filename:
        return jsonify({"error": "No file provided."}), 400
    try:
        data = ocr_client.extract_archive_fields(file.read(), file.mimetype)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(data)


@app.route("/staff", methods=["GET", "POST"])
def staff():
    return _list_view("staff", "Staff")


@app.route("/staff/lookup")
def staff_lookup():
    query = request.args.get("id", "").strip()
    match = None
    error = None
    if query:
        try:
            for row in sc.get_rows("staff"):
                if str(row.get("ID", "")).strip().lower() == query.lower():
                    match = row
                    break
        except Exception as exc:
            error = str(exc)
    return render_template("staff_lookup.html", query=query, match=match, error=error)


@app.route("/communications", methods=["GET", "POST"])
def communications():
    return _list_view("communications", "Communications")


@app.route("/comms", methods=["GET", "POST"])
def role_comms():
    viewer_role = session.get("staff_role", "")
    privileged = session.get("privileged", False)

    all_roles = []
    if privileged:
        try:
            all_roles = sorted(
                {(r.get("Role") or "").strip() for r in sc.get_rows("staff") if (r.get("Role") or "").strip()}
            )
        except Exception:
            all_roles = []

    selected_role = viewer_role
    if privileged:
        requested = request.values.get("role", "").strip()
        if requested:
            selected_role = requested
        elif not selected_role and all_roles:
            selected_role = all_roles[0]

    if request.method == "POST":
        post_role = selected_role if privileged else viewer_role
        message = request.form.get("Message", "").strip()
        if post_role and message:
            sc.add_row(
                "role_comms",
                {
                    "ID": "",
                    "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "Role": post_role,
                    "From": session.get("staff_name", ""),
                    "Message": message,
                },
            )
        return redirect(url_for("role_comms", role=post_role) if privileged else url_for("role_comms"))

    error = None
    messages = []
    if selected_role:
        try:
            rows = sc.get_rows("role_comms")
            messages = [r for r in rows if (r.get("Role") or "").strip().lower() == selected_role.lower()]
            messages.reverse()
        except Exception as exc:
            error = str(exc)

    return render_template(
        "role_comms.html",
        messages=messages,
        error=error,
        viewer_role=viewer_role,
        selected_role=selected_role,
        all_roles=all_roles,
        privileged=privileged,
    )


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


STICKER_QTY_DEFAULT = 18
STICKER_QTY_MAX = 200


def _sticker_qty():
    raw = request.form.get("quantity", "")
    try:
        qty = int(raw)
    except ValueError:
        qty = STICKER_QTY_DEFAULT
    return max(1, min(qty, STICKER_QTY_MAX))


@app.route("/print/stickers")
def print_stickers():
    return render_template(
        "print_stickers.html",
        default_qty=STICKER_QTY_DEFAULT,
        max_qty=STICKER_QTY_MAX,
    )


@app.route("/print/stickers/envelope-tags/pdf", methods=["POST"])
def print_envelope_tags_pdf():
    pdf_buf = cards.build_envelope_tags_pdf(_sticker_qty())
    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="scp_envelope_tags.pdf",
    )


@app.route("/print/stickers/logo/pdf", methods=["POST"])
def print_logo_stickers_pdf():
    pdf_buf = cards.build_logo_stickers_pdf(_sticker_qty())
    return send_file(
        pdf_buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="scp_logo_stickers.pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
