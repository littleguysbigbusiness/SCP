import os
from datetime import datetime, timezone

from flask import Flask, redirect, render_template, request, url_for

import sheets_client as sc

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

TILES = [
    {"key": "archives", "title": "Archives", "description": "SCP object records and containment data."},
    {"key": "staff", "title": "Staff", "description": "Personnel roster and clearance levels."},
    {"key": "communications", "title": "Communications", "description": "Internal message and incident log."},
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
