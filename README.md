# SCP Foundation Dashboard

A small Flask dashboard with three tiles — **Archives**, **Staff**, and **Communications** —
backed by a Google Sheet acting as the database. Deployed on Render as a web service.

## How it works

- Each tile corresponds to a tab in the Google Sheet (`Archives`, `Staff`, `Communications`).
- The app reads/writes rows via the Google Sheets API using a service account.
- If a tab doesn't exist yet, the app creates it automatically with the right headers
  the first time it's accessed.

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

## Environment variables

| Variable | Description |
|---|---|
| `GOOGLE_SHEET_ID` | The ID from the sheet URL: `docs.google.com/spreadsheets/d/<THIS_PART>/edit` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The full JSON key file contents, as a single-line string |
| `SECRET_KEY` | Any random string, used for Flask session signing |

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
3. Render will create a web service from `render.yaml`. It will prompt you for the two
   secret env vars (`GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`) since they're marked
   `sync: false` — paste in the values from the setup steps above.
4. Deploy. The start command is `gunicorn app:app`.

## Print Center

`/print` has three sub-sections. Keycards and Staff IDs both use
`templates/print_staff_select.html` — a checklist of staff (leave nothing checked to
include everyone) that posts to a `*_pdf` route which streams back a PDF built by
`cards.py` (ReportLab; no external services or fonts needed). 8 CR80-sized cards per
Letter page in both cases.

- **Keycards** (`/print/keycards`) — color-coded by Clearance Level.
- **Staff IDs** (`/print/staff-ids`) — Name/Role/Access Level/Role Rank/Born, a photo
  (from the `Photo URL` column if set and reachable, otherwise a placeholder silhouette),
  a Code128 barcode of the Staff ID, and an "Area" that's assigned deterministically at
  print time (seeded by Staff ID, so it's stable across reprints) since there's no Area
  column in the sheet — swap in a real column if you'd rather it be authored data.
- **Stickers** — placeholder page until a template is provided.

Staff ID generation added four columns to the Staff tab: `Age`, `Born`, `Role Rank`,
`Photo URL`. Existing sheets pick these up automatically (appended to the end of row 1)
the first time the app reads the Staff tab after deploy.

## Project structure

```
app.py              Flask routes
sheets_client.py     Google Sheets read/write helpers
cards.py             PDF generation (keycards; more templates to come)
templates/           Jinja templates (dashboard, per-tile list/add views, print center)
static/style.css      Styling
render.yaml           Render Blueprint (service + env var slots)
requirements.txt
```
