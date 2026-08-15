# SCP Foundation Dashboard

A small Flask dashboard with five tiles — **Archives**, **Staff**, **Communications**,
**Class-D Records**, and **Test Logs** — backed by a Google Sheet acting as the database.
Deployed on Render as a web service.

## How it works

- Each tile corresponds to a tab in the Google Sheet (`Archives`, `Staff`, `Communications`,
  `Class-D Records`, `Test Logs`).
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

- **O5 / Site Director** → full access: Dashboard, Archives, Staff, Communications, Class-D
  Records, Test Logs, Print, Edit History, Alarms (includes Announcements), Warhead, Site
  Status.
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

## Class-D Records + Test Logs

Two more privileged-only tiles, built on the same generic `_list_view`/`list.html` machinery
as Archives/Staff/Communications — no new templates needed.

- **Class-D Records** (`/class-d`) — `ID` (the D-Class designation, e.g. `D-9341`; there's
  deliberately no separate Name field, matching how the Foundation tracks D-Class), `Status`,
  `Assigned SCP`, `Intake Date`, `Termination Date`, `Notes`.
- **Test Logs** (`/test-logs`) — `ID`, `Date` (auto-fills to today if left blank, same as
  Archives' `Date Added`), `SCP`, `Subject`, `Procedure`, `Result`, `Researcher`.

## Editing records + Edit History

Archives, Staff, Communications, Class-D Records, and Test Logs rows can all be edited, not
just added. Each row in those tables has an **Edit** link (`/archives/edit/<id>`,
`/staff/edit/<id>`, `/communications/edit/<id>`, `/class-d/edit/<id>`,
`/test-logs/edit/<id>`) that opens a pre-filled form; saving it overwrites that row in
the Sheet in place via `sheets_client.update_row()`, which finds the row by matching the
`ID` column. Privileged-only, same as the tables themselves.

Every save that actually changes something logs a row to a new `Edit History` Sheet tab
(`Timestamp`, `Tab`, `Record ID`, `Editor`, `Changes`) — `Changes` is a plain-text diff of
just the fields that changed, e.g. `Area: "" -> "Area 12"`. View it at `/history` (linked
as "History" in the nav for privileged users), newest first.

## Site Alarms

A per-site security alert level system, same dynamic-per-value approach as Role Comms:
whatever text is in a staff member's `Site` column becomes a site with its own alarm state
— no fixed site list to configure. Current state per site lives in a `Site Alarms` Sheet
tab (`sheets_client.set_site_alarm()` upserts by `Site`, so there's exactly one live row per
site, not a growing log), and every level change is also logged to Edit History.

Seven levels, escalating severity (`ALARM_LEVELS` in `app.py`):

| Level | Label | Tier |
|---|---|---|
| 1 | Normal Protocol | calm |
| 2 | Minor SCP Breach | elevated |
| 3 | CI Detected | elevated |
| 4 | Mass SCP Breach | severe |
| 5 | Mass Dangerous SCP Breach | severe |
| 6 | CI Raid | critical |
| 7 | Evacuation | critical |

- **`/alarms`** (privileged-only, linked as "Alarms") — control panel: an overview table of
  every known site's current level, and a form to set a site's level (type/select the site,
  click a color-coded level button, optional broadcast message, then "Set Alert Level").
- **`/site-status`** (privileged-only, linked as "Site Status") — a fullscreen-friendly
  announcement screen with a site picker, so Site Directors and O5 can preview any site. The
  background color and animation intensity scale with the tier (`calm` = static, `elevated`
  = slow pulse, `severe` = fast pulse with glow, `critical` = hard flash). Uses the browser's built-in
  `SpeechSynthesis` API to read the alert aloud on load and whenever it changes — no paid TTS
  service involved. A "Fullscreen" button uses the Fullscreen API for wall-mounted displays.
  The screen polls `/site-status/data` (JSON) every 12 seconds to pick up changes without a
  full reload.
- Each level (2-7; level 1 is silent) has a looping alarm sound under
  `static/assets/alarms/` (`level-2-5.mp3` shared by levels 2-5, `level-6.mp3`, `level-7.mp3`
  — trimmed to a few minutes each so they're small enough to loop cleanly and to commit to
  the repo). Browsers block audio autoplay without a user gesture, so it only starts after
  clicking "Enable Alarm Audio" on the screen; after that it keeps looping and automatically
  swaps to the new level's clip (or silence, for level 1) whenever the level changes.

## Announcements

A separate, freeform broadcast channel from the alarm level itself — for messages that
aren't tied to changing a site's security state. Lives in its own `Announcements` Sheet tab
(`ID`, `Timestamp`, `Site`, `Message`, `Author`, `Countdown Seconds`, `Image URL`), an
append-only log rather than the one-row-per-site upsert that Site Alarms uses.

An announcement can optionally carry a countdown and/or an image, on top of the message:

- **Countdown** — the broadcast form takes minutes, stored as `Countdown Seconds`; like the
  warhead, remaining time is computed live from `Countdown Seconds` minus elapsed time since
  `Timestamp` (`_announcement_payload()`), not stored as a fixed target, so it's always
  correct on read. Shows as a ticking banner on Site Status.
- **Image** — either paste a URL or upload a file (both routes are supported; an upload
  takes priority if both are given). An uploaded file goes through
  `drive_client.upload_image()`, a sibling of the Archives scan uploader that returns a
  directly-embeddable `drive.google.com/uc?export=view&id=...` URL instead of
  `upload_scan()`'s human-facing viewer-page link — the wrong kind of link for an `<img src>`.
  When the latest announcement for a site has an image, it takes over the *entire* Site
  Status screen (all other content hidden) until a newer announcement replaces it - same
  precedence tier as a warhead detonation, which still wins if both are active at once.
  A message alone (no image) is enough to post - image and countdown are both optional, and
  a message is optional too as long as one of the other two is present.

- **`/alarms`** (privileged-only, linked as "Alarms") is a single combined Alarms +
  Announcements page: the level picker, an announcement broadcast form, one overview table
  showing each site's current level *and* latest announcement, and a recent-announcements
  history table. `/announcements` still exists as the POST target for that form (and
  redirects GET requests back to `/alarms` for anyone with an old link) but there's no
  separate page for it anymore.
- Shows up on the Site Status screen for any matching site (that exact site, or an "All
  Sites" post): a new one slides in as a temporary popup card and gets read aloud via the
  same `SpeechSynthesis` mechanism, then after a few seconds settles into a persistent "Site
  Broadcast" list (last 5, newest first) alongside an "Alarm History" list of past level
  changes for that site (pulled from Edit History, label extracted from the diff text via a
  regex). Each announcement gets a real generated `ID` (`uuid.uuid4().hex[:12]`, unlike Role
  Comms/Test Logs which leave `ID` blank) because the Site Status poller diffs on it to
  detect a genuinely new announcement — using `Timestamp` for that would fail if two
  announcements land in the same second. The control-button row (Fullscreen/Repeat
  Announcement/Enable Alarm Audio) hides itself while the screen is in fullscreen, via the
  CSS `:fullscreen` pseudo-class, so a wall-mounted display shows just the alert.

## Warhead

A per-site self-destruct, absolute last resort, in its own `Warheads` Sheet tab (`Site`,
`Status`, `Armed By`, `Armed At`, `Detonate At`, `Show Countdown`) upserted the same way as
Site Alarms - one live row per site (`sheets_client.set_warhead()`, sharing the
`_upsert_by_column()` helper that `set_site_alarm()` also uses now).

- **`/warhead`** (privileged-only, linked as "Warhead") — arming requires turning both "KEY
  1" and "KEY 2" toggle buttons before the red "Arm Warhead" button becomes clickable (a
  client-side gate for the classic two-key launch feel; the real security boundary is still
  the privileged-only route). A "Display countdown banner on Site Status screen" checkbox
  (checked by default) controls `Show Countdown` — uncheck it to arm silently, still forcing
  Level 7 and still detonating on schedule, just without the visible/audible countdown on
  that site's screen. Arming forces the site's alarm to Level 7 Evacuation and starts a
  5-minute countdown (`WARHEAD_ARM_SECONDS`), all logged to Edit History. Any O5/Site
  Director can Disarm an armed site before it reaches zero, or Reset a detonated one back to
  Safe. Each row also has a "Broadcast to TV Screens" link that opens that site's Site Status
  in a new tab.
- There's no background job - whether the countdown has reached zero is computed lazily
  whenever a site's warhead state is read (`_warhead_state()`), and the "detonated"
  transition is written back to the sheet at that point so it sticks from then on.
- Site Status reflects it live: while armed (and `Show Countdown` is on), a flashing
  countdown card sits inside the alarm panel itself — nested there specifically so it's still
  visible in fullscreen, along with everything else on the page (see below) — and a
  synthesized square-wave beep (Web Audio API `OscillatorNode`, no audio file) ticks once per
  second, gated behind the same "Enable Alarm Audio" button as the alarm-level sounds. On
  detonation, the whole screen swaps to a black "SITE DESTROYED" end state, announced via
  `SpeechSynthesis`, picked up automatically by the existing 12-second
  poll without needing a page reload.
- The Fullscreen button targets a wrapping `#status-root` div around the whole screen (alarm
  panel, destroyed-screen, and the announcement popup), not just the alarm panel itself -
  the Fullscreen API only shows the fullscreened element's own subtree, so anything outside
  it (the countdown banner used to be a sibling, not a child) would otherwise vanish the
  moment the screen goes fullscreen.

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
