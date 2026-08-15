import os
import uuid
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

# "tier" drives how urgently the Site Status screen animates (see .alarm-tier-*
# in style.css) - it escalates independently of the numeric level so e.g.
# levels 2-3 read as equally "elevated" even though only one number is higher.
# "sound" is a filename under static/assets/alarms/, looped on the Site Status
# screen until the level changes; None (level 1) plays nothing.
ALARM_LEVELS = {
    1: {
        "label": "Normal Protocol",
        "tier": "calm",
        "description": "Standard operations. No active threats. Continue routine duties.",
        "sound": None,
    },
    2: {
        "label": "Minor SCP Breach",
        "tier": "elevated",
        "description": "A contained anomaly has breached containment. Non-essential personnel remain clear of the affected wing.",
        "sound": "level-2-5.mp3",
    },
    3: {
        "label": "CI Detected",
        "tier": "elevated",
        "description": "Chaos Insurgency activity detected on or near the site. Increase security posture and verify all credentials.",
        "sound": "level-2-5.mp3",
    },
    4: {
        "label": "Mass SCP Breach",
        "tier": "severe",
        "description": "Multiple containment breaches in progress. Non-essential personnel proceed to designated shelter points.",
        "sound": "level-2-5.mp3",
    },
    5: {
        "label": "Mass Dangerous SCP Breach",
        "tier": "severe",
        "description": "Multiple hazardous anomalies are loose. All personnel proceed to designated shelter points immediately.",
        "sound": "level-2-5.mp3",
    },
    6: {
        "label": "CI Raid",
        "tier": "critical",
        "description": "Chaos Insurgency forces are engaging site security. All non-security personnel shelter in place.",
        "sound": "level-6.mp3",
    },
    7: {
        "label": "Evacuation",
        "tier": "critical",
        "description": "Evacuate the facility immediately via the nearest marked exit. This is not a drill.",
        "sound": "level-7.mp3",
    },
}


def _known_sites():
    sites = set()
    for tab in ("staff", "site_alarms"):
        try:
            for r in sc.get_rows(tab):
                s = (r.get("Site") or "").strip()
                if s:
                    sites.add(s)
        except Exception:
            pass
    return sorted(sites)


def _get_site_alarm(site):
    if not site:
        return None
    try:
        rows = sc.get_rows("site_alarms")
    except Exception:
        return None
    return next((r for r in rows if str(r.get("Site", "")) == str(site)), None)


def _site_alarm_state(site):
    row = _get_site_alarm(site)
    level = int(row["Level"]) if row and str(row.get("Level", "")).isdigit() else 1
    level = level if level in ALARM_LEVELS else 1
    info = ALARM_LEVELS[level]
    return {
        "site": site,
        "level": level,
        "label": info["label"],
        "tier": info["tier"],
        "description": info["description"],
        "sound": info["sound"],
        "message": (row.get("Message") if row else "") or "",
        "updated_by": (row.get("Updated By") if row else "") or "",
        "updated_at": (row.get("Updated At") if row else "") or "",
    }


ANNOUNCEMENT_ALL_SITES = "All Sites"


def _latest_announcement(site):
    if not site:
        return None
    try:
        rows = sc.get_rows("announcements")
    except Exception:
        return None
    relevant = [r for r in rows if r.get("Site") in (site, ANNOUNCEMENT_ALL_SITES)]
    return relevant[-1] if relevant else None


def _announcement_payload(row):
    if not row:
        return None
    return {
        "id": row.get("ID", ""),
        "message": row.get("Message", ""),
        "author": row.get("Author", ""),
        "timestamp": row.get("Timestamp", ""),
        "site": row.get("Site", ""),
    }


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
    {"key": "class_d", "title": "Class-D Records", "description": "D-Class personnel roster and assignments."},
    {"key": "test_logs", "title": "Test Logs", "description": "SCP testing and experiment log."},
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
        if key == "test_logs" and not row.get("Date"):
            row["Date"] = datetime.now(timezone.utc).date().isoformat()
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


def _summarize_changes(headers, old_row, new_values):
    parts = []
    for h in headers:
        old_v = str(old_row.get(h, ""))
        new_v = str(new_values.get(h, ""))
        if old_v != new_v:
            parts.append('{}: "{}" -> "{}"'.format(h, old_v, new_v))
    return "; ".join(parts)


def _edit_view(key, title, record_id):
    config = sc.TABS[key]
    headers = config["headers"]

    if request.method == "POST":
        new_values = {h: request.form.get(h, "").strip() for h in headers}
        old_row = sc.update_row(key, record_id, new_values)
        if old_row is not None:
            changes = _summarize_changes(headers, old_row, new_values)
            if changes:
                sc.add_row(
                    "edit_history",
                    {
                        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "Tab": config["title"],
                        "Record ID": record_id,
                        "Editor": session.get("staff_name", ""),
                        "Changes": changes,
                    },
                )
        return redirect(url_for(key))

    error = None
    row = None
    try:
        rows = sc.get_rows(key)
        row = next((r for r in rows if str(r.get("ID", "")) == str(record_id)), None)
    except Exception as exc:
        error = str(exc)
    if row is None and error is None:
        error = 'No record found with ID "{}".'.format(record_id)

    return render_template(
        "edit.html", title=title, headers=headers, row=row or {}, key=key, error=error, record_id=record_id
    )


@app.route("/archives", methods=["GET", "POST"])
def archives():
    return _list_view("archives", "Archives")


@app.route("/archives/edit/<record_id>", methods=["GET", "POST"])
def archives_edit(record_id):
    return _edit_view("archives", "Edit Archives Record", record_id)


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


@app.route("/staff/edit/<record_id>", methods=["GET", "POST"])
def staff_edit(record_id):
    return _edit_view("staff", "Edit Staff Record", record_id)


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


@app.route("/communications/edit/<record_id>", methods=["GET", "POST"])
def communications_edit(record_id):
    return _edit_view("communications", "Edit Communications Record", record_id)


@app.route("/class-d", methods=["GET", "POST"])
def class_d():
    return _list_view("class_d", "Class-D Records")


@app.route("/class-d/edit/<record_id>", methods=["GET", "POST"])
def class_d_edit(record_id):
    return _edit_view("class_d", "Edit Class-D Record", record_id)


@app.route("/test-logs", methods=["GET", "POST"])
def test_logs():
    return _list_view("test_logs", "Test Logs")


@app.route("/test-logs/edit/<record_id>", methods=["GET", "POST"])
def test_logs_edit(record_id):
    return _edit_view("test_logs", "Edit Test Log", record_id)


@app.route("/history")
def edit_history():
    error = None
    rows = []
    try:
        rows = list(reversed(sc.get_rows("edit_history")))
    except Exception as exc:
        error = str(exc)
    return render_template("history.html", rows=rows, error=error)


@app.route("/alarms", methods=["GET", "POST"])
def alarms():
    if request.method == "POST":
        site = request.form.get("Site", "").strip()
        message = request.form.get("Message", "").strip()
        try:
            level = int(request.form.get("Level", "0"))
        except ValueError:
            level = 0

        if site and level in ALARM_LEVELS:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            old_row = sc.set_site_alarm(site, level, message, session.get("staff_name", ""), timestamp)
            old_level = str(old_row.get("Level", "")) if old_row else ""
            old_message = old_row.get("Message", "") if old_row else ""
            changes = []
            if old_level != str(level):
                old_label = ALARM_LEVELS.get(int(old_level), {}).get("label", "none") if old_level.isdigit() else "none"
                changes.append('Level: "{}" -> "{}: {}"'.format(old_label, level, ALARM_LEVELS[level]["label"]))
            if old_message != message:
                changes.append('Message: "{}" -> "{}"'.format(old_message, message))
            if changes:
                sc.add_row(
                    "edit_history",
                    {
                        "Timestamp": timestamp,
                        "Tab": "Site Alarms",
                        "Record ID": site,
                        "Editor": session.get("staff_name", ""),
                        "Changes": "; ".join(changes),
                    },
                )
        return redirect(url_for("alarms"))

    error = None
    known_sites = []
    try:
        known_sites = _known_sites()
    except Exception as exc:
        error = str(exc)

    statuses = [_site_alarm_state(site) for site in known_sites]

    return render_template(
        "alarms.html", statuses=statuses, levels=ALARM_LEVELS, known_sites=known_sites, error=error
    )


@app.route("/site-status")
def site_status():
    known_sites = _known_sites()
    selected_site = request.args.get("site", "").strip() or (known_sites[0] if known_sites else "")

    state = _site_alarm_state(selected_site) if selected_site else None
    announcement = _announcement_payload(_latest_announcement(selected_site)) if selected_site else None

    return render_template(
        "site_status.html",
        state=state,
        announcement=announcement,
        selected_site=selected_site,
        known_sites=known_sites,
    )


@app.route("/site-status/data")
def site_status_data():
    selected_site = request.args.get("site", "").strip()

    if not selected_site:
        return jsonify({"error": "No site to report on."}), 404

    data = _site_alarm_state(selected_site)
    data["announcement"] = _announcement_payload(_latest_announcement(selected_site))
    return jsonify(data)


@app.route("/announcements", methods=["GET", "POST"])
def announcements():
    if request.method == "POST":
        site = request.form.get("Site", "").strip() or ANNOUNCEMENT_ALL_SITES
        message = request.form.get("Message", "").strip()
        if message:
            sc.add_row(
                "announcements",
                {
                    # A real unique ID (unlike Role Comms, which leaves it
                    # blank) because the Site Status poller diffs on it to
                    # detect a new announcement - two posts in the same
                    # second would otherwise look identical.
                    "ID": uuid.uuid4().hex[:12],
                    "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "Site": site,
                    "Message": message,
                    "Author": session.get("staff_name", ""),
                },
            )
        return redirect(url_for("announcements"))

    error = None
    rows = []
    known_sites = []
    try:
        rows = list(reversed(sc.get_rows("announcements")))
        known_sites = _known_sites()
    except Exception as exc:
        error = str(exc)

    return render_template(
        "announcements.html",
        rows=rows,
        known_sites=known_sites,
        error=error,
        all_sites_label=ANNOUNCEMENT_ALL_SITES,
    )


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
