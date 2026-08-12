import json
import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID env var is not set")
    return get_client().open_by_key(sheet_id)


def get_worksheet(key):
    config = TABS[key]
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(config["title"])
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=config["title"], rows=200, cols=len(config["headers"]))
        ws.append_row(config["headers"])
        return ws

    values = ws.get_values("1:1")
    if not values or not values[0]:
        ws.append_row(config["headers"])
    return ws


def get_rows(key):
    ws = get_worksheet(key)
    return ws.get_all_records()


def add_row(key, row_dict):
    headers = TABS[key]["headers"]
    ws = get_worksheet(key)
    ws.append_row([row_dict.get(h, "") for h in headers])
