import json
import os
import time

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Google's default Sheets API quota is 60 read requests/min per user. Without
# caching, a single dashboard load (3 tiles) can burn 10+ reads, so worksheet
# handles and row data are cached in memory for the life of the process.
ROWS_CACHE_TTL = 20

TABS = {
    "archives": {
        "title": "Archives",
        "headers": ["ID", "Designation", "Object Class", "Description", "Containment Procedures", "Date Added"],
    },
    "staff": {
        "title": "Staff",
        "headers": ["ID", "Name", "Role", "Clearance Level", "Site", "Status", "Contact"],
    },
    "communications": {
        "title": "Communications",
        "headers": ["ID", "Timestamp", "From", "To", "Subject", "Message", "Priority"],
    },
}

_client = None
_spreadsheet = None
_worksheets = {}
_rows_cache = {}  # key -> (fetched_at, rows)


def get_client():
    global _client
    if _client is not None:
        return _client
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")
    info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    _client = gspread.authorize(creds)
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
