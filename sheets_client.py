import json
import os
import time

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Google's default Sheets API quota is 60 read requests/min per user. Without
# caching, a single dashboard load (3 tiles) can burn 10+ reads, so worksheet
# handles and row data are cached in memory for the life of the process.
ROWS_CACHE_TTL = 20

TABS = {
    "archives": {
        "title": "Archives",
        "headers": [
            "ID",
            "Designation",
            "Object Class",
            "Description",
            "Containment Procedures",
            "Date Added",
            "Scan URL",
        ],
    },
    "staff": {
        "title": "Staff",
        "headers": [
            "ID",
            "Name",
            "Role",
            "Clearance Level",
            "Site",
            "Status",
            "Contact",
            "Age",
            "Born",
            "Role Rank",
            "Photo URL",
            "Area",
        ],
    },
    "communications": {
        "title": "Communications",
        "headers": ["ID", "Timestamp", "From", "To", "Subject", "Message", "Priority"],
    },
    "class_d": {
        "title": "Class-D Records",
        "headers": ["ID", "Status", "Assigned SCP", "Intake Date", "Termination Date", "Notes"],
    },
    "test_logs": {
        "title": "Test Logs",
        "headers": ["ID", "Date", "SCP", "Subject", "Procedure", "Result", "Researcher"],
    },
    "role_comms": {
        "title": "Role Comms",
        "headers": ["ID", "Timestamp", "Role", "From", "Message"],
    },
    "edit_history": {
        "title": "Edit History",
        "headers": ["Timestamp", "Tab", "Record ID", "Editor", "Changes"],
    },
    "site_alarms": {
        "title": "Site Alarms",
        "headers": ["Site", "Level", "Message", "Updated By", "Updated At"],
    },
    "announcements": {
        "title": "Announcements",
        "headers": ["ID", "Timestamp", "Site", "Message", "Author", "Countdown Seconds", "Image URL"],
    },
    "warheads": {
        "title": "Warheads",
        "headers": ["Site", "Status", "Armed By", "Armed At", "Detonate At", "Show Countdown"],
    },
    "screen_control": {
        "title": "Screen Control",
        # Countdown Set At and Audio Set At are each their own column,
        # separate from Set By - image/countdown/audio are cleared
        # independently, and both the countdown's remaining-time
        # calculation and audio's "is this a new play request" check need
        # their own timestamp to survive an unrelated field being cleared.
        "headers": [
            "Site",
            "Image URL",
            "Countdown Label",
            "Countdown Seconds",
            "Countdown Set At",
            "Audio URL",
            "Loop Audio",
            "Audio Set At",
            "Set By",
        ],
    },
}

_credentials = None
_client = None
_spreadsheet = None
_worksheets = {}
_rows_cache = {}  # key -> (fetched_at, rows)


def get_credentials():
    global _credentials
    if _credentials is not None:
        return _credentials
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")
    info = json.loads(creds_json)
    _credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    return _credentials


def get_client():
    global _client
    if _client is not None:
        return _client
    _client = gspread.authorize(get_credentials())
    return _client


def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID env var is not set")
    _spreadsheet = get_client().open_by_key(sheet_id)
    return _spreadsheet


def get_worksheet(key):
    if key in _worksheets:
        return _worksheets[key]

    config = TABS[key]
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(config["title"])
        values = ws.get_values("1:1")
        if not values or not values[0]:
            ws.append_row(config["headers"])
        else:
            # Schema additions (new columns appended to TABS[...]["headers"])
            # get bolted onto the end of the existing header row here, so
            # older sheets pick up new fields without disturbing column
            # positions add_row()/append_row() already rely on.
            existing = values[0]
            missing = [h for h in config["headers"] if h not in existing]
            if missing:
                start_col = len(existing) + 1
                end_col = start_col + len(missing) - 1
                if ws.col_count < end_col:
                    ws.add_cols(end_col - ws.col_count)
                cell_range = "{}:{}".format(
                    gspread.utils.rowcol_to_a1(1, start_col),
                    gspread.utils.rowcol_to_a1(1, end_col),
                )
                ws.update(range_name=cell_range, values=[missing])
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=config["title"], rows=200, cols=len(config["headers"]))
        ws.append_row(config["headers"])

    _worksheets[key] = ws
    return ws


def get_rows(key):
    now = time.time()
    cached = _rows_cache.get(key)
    if cached and now - cached[0] < ROWS_CACHE_TTL:
        return cached[1]

    ws = get_worksheet(key)
    rows = ws.get_all_records()
    _rows_cache[key] = (now, rows)
    return rows


def add_row(key, row_dict):
    headers = TABS[key]["headers"]
    ws = get_worksheet(key)
    ws.append_row([row_dict.get(h, "") for h in headers])
    _rows_cache.pop(key, None)


def _write_row(ws, headers, row_index, values_dict):
    values = [values_dict.get(h, "") for h in headers]
    start = gspread.utils.rowcol_to_a1(row_index, 1)
    end = gspread.utils.rowcol_to_a1(row_index, len(headers))
    ws.update(range_name="{}:{}".format(start, end), values=[values])


def update_row(key, record_id, new_values):
    """Overwrites the row whose ID matches record_id with new_values.

    Returns the row's prior values (a dict), or None if no row with that ID
    was found.
    """
    headers = TABS[key]["headers"]
    ws = get_worksheet(key)
    records = ws.get_all_records()
    for i, record in enumerate(records):
        if str(record.get("ID", "")) == str(record_id):
            _write_row(ws, headers, i + 2, new_values)  # +1 header row, +1 1-indexing
            _rows_cache.pop(key, None)
            return record
    return None


def _upsert_by_column(key, column, value, new_values):
    """Overwrites the row whose `column` matches `value` with new_values, or
    appends a new row if none matched.

    Returns the row's prior values (a dict), or None if it was newly created.
    """
    headers = TABS[key]["headers"]
    ws = get_worksheet(key)
    records = ws.get_all_records()
    for i, record in enumerate(records):
        if str(record.get(column, "")) == str(value):
            _write_row(ws, headers, i + 2, new_values)
            _rows_cache.pop(key, None)
            return record
    ws.append_row([new_values.get(h, "") for h in headers])
    _rows_cache.pop(key, None)
    return None


def set_site_alarm(site, level, message, updated_by, updated_at):
    return _upsert_by_column(
        "site_alarms",
        "Site",
        site,
        {"Site": site, "Level": level, "Message": message, "Updated By": updated_by, "Updated At": updated_at},
    )


def set_warhead(site, status, armed_by, armed_at, detonate_at, show_countdown=True):
    return _upsert_by_column(
        "warheads",
        "Site",
        site,
        {
            "Site": site,
            "Status": status,
            "Armed By": armed_by,
            "Armed At": armed_at,
            "Detonate At": detonate_at,
            "Show Countdown": "Yes" if show_countdown else "No",
        },
    )


def set_screen_control(site, fields):
    """Merges `fields` (a partial dict of columns to change) onto the site's
    existing Screen Control row - image/countdown/audio are set and cleared
    independently, so callers only pass the columns they're actually
    touching and everything else is left as-is."""
    headers = TABS["screen_control"]["headers"]
    ws = get_worksheet("screen_control")
    records = ws.get_all_records()
    current = next((r for r in records if str(r.get("Site", "")) == str(site)), None)
    merged = {h: (current.get(h, "") if current else "") for h in headers}
    merged["Site"] = site
    merged.update(fields)
    return _upsert_by_column("screen_control", "Site", site, merged)
