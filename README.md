# SCP Foundation Dashboard

A small Flask dashboard with three tiles — **Archives**, **Staff**, and **Communications** —
backed by a Google Sheet acting as the database. Deployed on Render as a web service.

## How it works

- Each tile corresponds to a tab in the Google Sheet (`Archives`, `Staff`, `Communications`).
- The app reads/writes rows via the Google Sheets API using a service account.
- If a tab doesn't exist yet, the app creates it automatically with the right headers
  the first time it's accessed.

## Login and access control

Every page except `/login` requires a session (`app.py`'s `before_request` hook, logic in
`auth.py`). Logging in takes a **Name** (matched against the `Name` column in the Staff
sheet, case-insensitive) and a **password shared by everyone** — `STAFF_LOGIN_PASSWORD`,
defaulting to `123456`. There's no per-user password; anyone who knows the shared password
and a valid staff name can log in as that person. That's a low security bar by design for a
small home-server tool, but change `STAFF_LOGIN_PASSWORD` to something non-default if this
is reachable from outside your own network.

Who gets what after logging in is decided by `auth.is_privileged()`, which checks the
matched staff row's `Role`, `Role Rank`, and `Clearance Level` columns for "O5" or "site
director" (case-insensitive substring match):

- **O5 / Site Director** → full access: Dashboard, Archives, Staff, Communications, Print.
- **Everyone else** → only **Staff Duties** (`/staff-duties`), a static duties reference
  page. Any other URL redirects there.

If your sheet encodes O5/Director status differently, adjust the check in `auth.py`.

## One-time setup: Google service account

The app needs its own Google identity with edit access to your sheet (the "anyone with
the link can edit" sharing setting doesn't give an API/server credential).

1. Go to the [Google Cloud Console](https://console.cloud.google.com/), create a project
   (or reuse one).
2. Enable the **Google Sheets API** for that project (APIs & Services → Enable APIs → search
   "Google Sheets API").
3. Create a **Service Account** (APIs & Services → Credentials → Create Credentials →
   Service Account).
4. Open the service account → **Keys** → **Add Key** → **Create new key** → JSON. This
   downloads a `.json` credentials file — keep it secret, never commit it.
5. Copy the service account's email address (looks like
   `something@project-id.iam.gserviceaccount.com`).
6. Open your Google Sheet and share it with that email address, with **Editor** access.
7. Copy the full contents of the downloaded JSON file — you'll paste it as the
   `GOOGLE_SERVICE_ACCOUNT_JSON` environment variable (see below).

### Also required for Archives → Scan Document

Uploaded scans need somewhere to live. Service accounts have **no Drive storage quota of
their own** — uploads have to land in a folder a real Google account owns, shared with the
service account:

1. In Google Drive, create a folder (e.g. "SCP Archive Scans").
2. Share it with the same service account email from step 5 above, with **Editor** access.
3. Open the folder and copy its ID from the URL:
   `drive.google.com/drive/folders/<THIS_PART>`.
4. Enable the **Google Drive API** in the same Cloud project (APIs & Services → Enable APIs
   → search "Google Drive API").
5. Set that ID as the `GOOGLE_DRIVE_FOLDER_ID` environment variable (see below).

If this isn't set up, `/archives/scan` still works for everything except the file upload —
it shows an error and leaves the Archives entry unsaved rather than saving a broken link.

### Also required for document reading (OCR)

The "Read with OCR" button on the Scan Document page runs text recognition locally via
Tesseract — no external API or account needed. It works best on documents formatted like
a Foundation article (`Item #:`, `Object Class:`, `Special Containment Procedures:`,
`Description:` labels), since those labels are what it uses to fill in the fields.

- **On Render**: the service runs as a Docker deploy (`Dockerfile` at the repo root), which
  installs `tesseract-ocr` and `poppler-utils` as part of the image build, so no setup is
  needed. Render's native Python runtime can't install system packages at build time (its
  build filesystem is read-only outside of `pip`), which is why this needs Docker instead
  of a plain `buildCommand`.
- **Running locally**: install Tesseract OCR yourself and make sure it's on your `PATH`.
  - Windows: install the [UB Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki).
  - macOS: `brew install tesseract poppler`
  - Linux: `apt install tesseract-ocr poppler-utils`

  `poppler` is only needed for PDF uploads (it renders PDF pages to images before OCR).

Without Tesseract installed, the upload/save flow still works — the OCR button just shows
an error instead of filling in the fields, and you fall back to typing them in by hand.

## Environment variables

| Variable | Description |
|---|---|
| `GOOGLE_SHEET_ID` | The ID from the sheet URL: `docs.google.com/spreadsheets/d/<THIS_PART>/edit` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The full JSON key file contents, as a single-line string |
| `GOOGLE_DRIVE_FOLDER_ID` | ID of a Drive folder shared with the service account (Editor), for Archives → Scan Document uploads |
| `SECRET_KEY` | Any random string, used for Flask session signing |
| `STAFF_LOGIN_PASSWORD` | Shared login password for all staff. Defaults to `123456` if unset — **change this on Render** since it's the one thing gating the whole site |

See `.env.example` for the format.

## Running locally

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # then fill in real values
```

Load the `.env` values into your shell (e.g. via `python-dotenv`, or set them manually),
then:

```bash
python app.py
```

Visit http://localhost:5000

## Deploying to Render

This repo includes a `render.yaml` blueprint.

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. In Render, choose **New → Blueprint**, point it at this repo.
3. Render will create a web service from `render.yaml`. It will prompt you for the secret
   env vars (`GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID`)
   since they're marked `sync: false` — paste in the values from the setup steps above.
4. Deploy. Render builds the `Dockerfile` and starts it with `gunicorn app:app`, per the
   Dockerfile's `CMD`.

## Print Center

`/print` has three sub-sections. Keycards and Staff IDs both use
`templates/print_staff_select.html` — a checklist of staff (leave nothing checked to
include everyone) that posts to a `*_pdf` route which streams back a PDF built by
`cards.py` (ReportLab; no external services or fonts needed). 8 CR80-sized cards per
Letter page in both cases.

- **Keycards** (`/print/keycards`) — modeled on the classic SCP wiki keycard set: colored
  top band (wordmark, emblem, tagline, a QR code encoding the Staff ID, arrow icon), white
  "LEVEL n" band with the standard warning text, solid color footer. Numbered Clearance
  Levels (0-5) get their canonical color with black text; anything else (blank, "O5", or
  unrecognized) falls back to the dark blue undesignated card with white text.
- **Staff IDs** (`/print/staff-ids`) — Name/Role/Access Level/Role Rank/Born, a photo
  (from the `Photo URL` column if set and reachable, otherwise a plain "N/A" placeholder),
  a Code128 barcode of the Staff ID, and an "Area" printed from the `Area` column. If left
  blank for a given staff member, it falls back to one assigned deterministically at print
  time (seeded by Staff ID, so it's stable across reprints) rather than printing nothing.
- **Stickers** (`/print/stickers`) — not staff data, just a quantity picker. Two kinds,
  sized to fit a small envelope:
  - **Envelope Tag** — a blank To/From/Mail Back To/Address/Notes label, filled in by hand
    after printing, doubles as the envelope seal.
  - **SCP Logo Sticker** — plain Foundation seal.

Staff ID generation added five columns to the Staff tab: `Age`, `Born`, `Role Rank`,
`Photo URL`, `Area`. Existing sheets pick these up automatically (appended to the end of row 1,
growing the sheet's column count if needed) the first time the app reads the Staff tab
after deploy.

The Foundation emblem (`static/assets/scp_logo.svg`, the official mark from the SCP wiki,
CC BY-SA per the wiki's licensing) is rendered onto cards via `svglib` — parsed once into
a ReportLab Drawing, then deep-copied and recolored per use (e.g. white on a dark badge
header, black elsewhere) instead of rasterizing to a fixed-color PNG. Used on Staff IDs,
Keycards, and the SCP Logo Sticker.

## Role Comms

`/comms` (linked as "Role Comms" in the nav, reachable by every logged-in staff member —
it's in `auth.UNPRIVILEGED_ENDPOINTS`, unlike the rest of the privileged-only tiles) is a
simple message board scoped to a staff member's `Role` column value in the Staff sheet.
There's no fixed list of roles — whatever text is in a given staff member's `Role` field
becomes their channel, so a new role just works the first time someone with that role logs
in and posts.

- **Regular staff** only ever see and post to their own role's channel (from
  `session["staff_role"]`, set at login) — no picker, no way to see other channels.
- **Site Directors and O5** (already privileged everywhere else) get a channel dropdown
  populated from every distinct `Role` value on file, and can read/post to any of them.
- Messages live in their own `Role Comms` Sheet tab (`sheets_client.py`'s `role_comms`
  entry: `ID`, `Timestamp`, `Role`, `From`, `Message`) — separate from the general
  `Communications` incident log, which stays privileged-only.

## Editing records + Edit History

Archives, Staff, and Communications rows can now be edited, not just added. Each row in
those tables has an **Edit** link (`/archives/edit/<id>`, `/staff/edit/<id>`,
`/communications/edit/<id>`) that opens a pre-filled form; saving it overwrites that row in
the Sheet in place via `sheets_client.update_row()`, which finds the row by matching the
`ID` column. Privileged-only, same as the tables themselves.

Every save that actually changes something logs a row to a new `Edit History` Sheet tab
(`Timestamp`, `Tab`, `Record ID`, `Editor`, `Changes`) — `Changes` is a plain-text diff of
just the fields that changed, e.g. `Area: "" -> "Area 12"`. View it at `/history` (linked
as "History" in the nav for privileged users), newest first.

## Staff Lookup

`/staff/lookup` (linked from the Staff page) is a single ID input, auto-focused, that
submits on Enter — which is exactly how a USB/Bluetooth barcode scanner behaves (it types
the scanned text, then sends Enter as if from a keyboard). Scanning a keycard's barcode or
typing a Staff ID both look up and display that person's full record. No match just shows
"not found" rather than erroring.

There's also a **Scan with Camera** button that uses the browser's `BarcodeDetector` API
(Code128 + QR) directly against the device camera — no external library, no server round
trip for the scan itself. It's only supported in Chromium-based browsers (Chrome/Edge,
notably including Android) — Safari and Firefox don't implement `BarcodeDetector`, so the
button shows a message pointing to USB-scanner/manual-entry instead of failing silently.

## Archives → Scan Document

`/archives/scan` (linked from the Archives page) uploads a photo or PDF of a document
straight into a new Archives row. The file goes to Google Drive via `drive_client.py`
(using the same service account as the Sheet, plus the Drive scope/folder from the setup
section above) and the resulting link is stored in a `Scan URL` column, shown as a "View
scan" link in the Archives table. `Date Added` auto-fills with today's date if left blank.
Uploads are capped at 10MB (`MAX_CONTENT_LENGTH`). If the Drive upload fails (e.g. the
folder isn't shared yet), the form re-shows with an error and nothing is saved — no entry
with a dead link.

**Read with OCR** — pick a file, then click "Read with OCR" (it also fires automatically on
file selection). The browser sends the file to `/archives/scan/analyze`, which runs local
text recognition (`ocr_client.py`, Tesseract via `pytesseract`; PDFs are rendered to images
first with `pdf2image`) and fills in Designation / Object Class / Description / Containment
Procedures by matching the OCR'd text against those labels. This is a separate, Drive-free
request purely for reading the file — nothing is saved or uploaded until you review the
filled-in fields and click **Save to Archives**, which does the actual Drive upload. Fields
it can't find a label for come back blank rather than guessed. It only recognizes documents
formatted with the classic Foundation article labels — plain prose or a different layout
won't map cleanly onto the fields.

## Project structure

```
app.py              Flask routes + login/access-control hook
auth.py               Login matching + O5/Site Director privilege check
sheets_client.py     Google Sheets read/write helpers
drive_client.py       Google Drive upload helper (Archives scans)
ocr_client.py           Tesseract OCR that reads scanned documents
cards.py             PDF generation (keycards, staff IDs, stickers)
templates/           Jinja templates (dashboard, per-tile list/add views, print center,
                      staff lookup, archives scan, login, staff duties)
static/style.css      Styling
static/assets/         Bundled static assets (Foundation emblem SVG)
render.yaml           Render Blueprint (Docker service + env var slots)
Dockerfile             Image build: installs Tesseract/Poppler, then the app
requirements.txt
```
