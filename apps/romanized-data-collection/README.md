# Akshar: Romanized Nepali data collection

A small web app in which native speakers independently type Devanagari Nepali items the way they would in
chat. It produces the natural-romanization (R-nat) condition of the Paper 1 benchmark.

**Design:** 241 questions (180 NeCCo = 30 per category, 61 Belebele in 34 passages), each written by 3 of the active
writers (`WRITERS_PER_UNIT`); with 3 writers everyone writes everything, about 1,330 boxes (5–6 hours). The sample
is chosen from a seeded pool of 600 questions; the rest are *retired* (not given to writers, kept for later). To change
the size, run `python -m app.select_subset --necco-per-category N --belebele-questions M` from `backend/` (dry run;
add `--apply`). Units already started are always kept.

- `backend/`: FastAPI + SQLAlchemy on PostgreSQL (Aiven). Seeds the 552 sampled units (3,182 boxes) on first start.
- `frontend/`: React (Vite). Writer page and admin page.

## What it does

**Writers** log in, fill in a short "About you" form with consent, read the instructions, and type each item.
- They see only Devanagari: never the existing romanization, the source, or the answer.
- Each writer gets an even share of the items, in a different random order. 20 items repeat later under a
  different number, so we can measure how consistently one person spells the same text.
- Pasting is blocked and counted, Devanagari input is rejected, and browser autocorrect and spellcheck are off.
- Work saves when a box loses focus or when they press Save. Active typing time is recorded per item.

**Admin** (credentials from `ADMIN_USERNAME` / `ADMIN_PASSWORD`):
- Overview of each writer's progress, and a notification log with a test button.
- Create writers (each gets an anonymous code W1, W2, …), reset passwords, and disable or enable accounts. Whenever
  the set of active writers changes, the items nobody has started are shared out again evenly; work a writer has
  started stays with them, and items a disabled writer finished still count.
- Add items (optional passage plus multiple-choice questions, in Devanagari). New items are appended to every
  writer's list. Items with no responses yet can be deleted.
- Download the dataset: responses as CSV or JSONL, and writer profiles as CSV.

**Notifications** go out when a writer finishes everything, and again when all active writers have finished, by
email (SMTP) and/or a Discord or Slack webhook.

## Run locally

```bash
# backend (from backend/)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows; use .venv/bin/pip elsewhere
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# frontend (from frontend/)
npm install
npm run dev                                           # http://localhost:5173, /api is proxied to :8000
```

The backend reads `../.env` (this folder) and `backend/.env`. See `.env.example` for every variable.
Tests run on a temporary SQLite database: `python -m pytest -q tests` (from `backend/`).

## Deploy on Vercel (two projects from the same repository)

1. **Backend**: New Project → Root Directory `apps/romanized-data-collection/backend`, Framework preset "Other".
   Add the environment variables from `.env` (at least `AIVEN_DATABASE_URL`, `ADMIN_USERNAME`,
   `ADMIN_PASSWORD`, `SECRET_KEY`). Deploy, then open `https://<backend>.vercel.app/api/health`, which should
   return `{"ok": true}`.
2. **Frontend**: New Project → Root Directory `apps/romanized-data-collection/frontend`, Framework preset "Vite".
   Set `VITE_API_URL=https://<backend>.vercel.app`. Deploy.
3. Back in the backend project, set `FRONTEND_ORIGINS` and `APP_URL` to the frontend URL and redeploy.

**Speed:** every database query is a round trip between the backend function and the database, so the function
must run in the Vercel region closest to the Aiven database. `backend/vercel.json` pins it to `bom1` (Mumbai), the
closest region to an Aiven database in India (`do-blr`, `aws-ap-south-1`, `google-asia-south1`). If the database
is elsewhere, change it (for example `sin1` for Singapore). With the default US region, every query took
about 220 ms instead of about 20 ms.

The backend can also run on any server that runs Python (Render, Railway, a VPS) with
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`; only `VITE_API_URL` changes.

## Notifications

- **Discord** (easiest): Server settings → Integrations → Webhooks → New webhook → copy the URL into
  `NOTIFY_WEBHOOK_URL`.
- **Gmail**: turn on 2-step verification, create an App Password, then set `SMTP_HOST=smtp.gmail.com`,
  `SMTP_USER=<gmail>`, `SMTP_PASSWORD=<app password>`, `NOTIFY_EMAIL=<where to send>`.

Use "Send test notification" on the admin overview to check the setup.

## Dataset export columns

`writer_code, writer_username, unit_order, unit_key, repeat_of, source, category, item_id, field, devanagari,
romanized, r_std, answer, note, edit_count, created_at, updated_at, unit_active_ms, unit_paste_blocked`

One row per writer per box. `field` is `passage`, `question` or `A`–`D`. `r_std` is the existing romanization
from Belebele or NeCCo (empty for NeCCo Festivals, which has none). `repeat_of` marks the hidden repeats. Publish
`writer_code`, not `writer_username`.

## Changing the seeded sample

The seed (`backend/seed/items.json`) is generated from the raw data by `scripts/export_seed.py` in the project
root, using the same fixed-seed sample as `scripts/prepare_annotation.py`. It is loaded only into an empty
database; after that, add items through the admin page. To replace the items in a database that has no responses
yet, run `python -m app.reseed` from `backend/` (it refuses to run once any response exists).
