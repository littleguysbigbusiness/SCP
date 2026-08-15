import os

import sheets_client as sc

LOGIN_PASSWORD = os.environ.get("STAFF_LOGIN_PASSWORD", "123456")

# Routes reachable without being logged in.
OPEN_ENDPOINTS = {"login", "static"}

# Routes any logged-in staff member can reach, privileged or not.
UNPRIVILEGED_ENDPOINTS = {"staff_duties", "logout", "role_comms", "site_status", "site_status_data"}

PRIVILEGED_KEYWORDS = ("o5", "site director")


def find_staff_by_name(name):
    target = name.strip().lower()
    for row in sc.get_rows("staff"):
        if str(row.get("Name", "")).strip().lower() == target:
            return row
    return None


def is_privileged(staff_row):
    text = " ".join(
        str(staff_row.get(field, "")) for field in ("Role", "Role Rank", "Clearance Level")
    ).lower()
    return any(keyword in text for keyword in PRIVILEGED_KEYWORDS)
