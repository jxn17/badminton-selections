# Badminton Trials 2026 — Draws & Scoring

Selection-trial draw and live-scoring tool. Entrants come from a Google Form
(category is taken from the **Gender** field). Men are split into **four balanced
groups (A–D)**, women run as a single **128-draw**. Public pages are read-only;
admins sign in with a **shared access code** to import, build draws, enter scores,
schedule matches, flag shortlist players, swap players, and add walk-ins.

- **Frontend:** React 18 + TypeScript + Tailwind + Vite
- **Backend:** FastAPI + SQLAlchemy 2 + Pydantic v2
- **Database:** PostgreSQL
- **Deploy:** single-origin (FastAPI serves the built SPA) — one Railway service + Postgres

```
backend/    FastAPI app, draw + grouping + scoring engines, tests
frontend/   React SPA (group navbar, editable bracket cards, admin toolbar)
sample_data/  FAKE sample CSV + generator (the real entrant file is never committed)
Dockerfile  all-in-one image (builds frontend, served by FastAPI) — used by Railway
docker-compose.yml  local all-in-one (app + Postgres)
```

---

## What it does

- **Dedup:** re-submissions are merged (normalized phone per category; falls back to
  registration number, then name, so nobody with a bad phone is lost). Idempotent import.
- **Fair groups:** the 227 men are snake-drafted into A–D by strength tier, so
  Nationals/States and District players are spread evenly — no stacked group.
- **Editable bracket cards:** admins type scores inline; the winner advances live.
  Re-editing a decided match safely re-advances (or blocks if the next match started).
- **RET**, **match scheduling** (free-text time/court per card), **flag/shortlist**
  (⭐ a player so they're kept even if they lose a good match), **swap players**
  (rebalance who-plays-whom before matches start), and **walk-ins** (add a spot
  entry; auto-slotted into an open bye).
- **Phone numbers** show to signed-in admins only — never on the public page.
- **Multi-admin:** the shared code lets several organizers edit at once; the bracket
  auto-refreshes every 15s so they see each other's updates. Each admin enters a
  name that's recorded in the audit log with every change.

---

## Run locally

### Option A — all-in-one with Docker (mirrors production)
```bash
docker compose up --build
```
Open <http://localhost:8000>. Set a code first if you like:
`ADMIN_ACCESS_CODE=mycode docker compose up --build`.

### Option B — dev servers (hot reload)
Backend (needs a Postgres, or use SQLite for a quick spin):
```bash
cd backend
python -m venv .venv && .venv/Scripts/activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=sqlite:///./trials.db ADMIN_ACCESS_CODE=trials2026 SECRET_KEY=dev \
  uvicorn app.main:app --reload --port 8000
python seed.py     # optional: load the fake sample + build draws
```
Frontend:
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api -> :8000)
```

---

## Deploy to Railway (single service + Postgres)

1. Push this repo to GitHub (already done).
2. In Railway: **New Project → Deploy from GitHub repo** → pick this repo. It
   detects the root `Dockerfile` (builds the frontend and serves it from FastAPI).
3. **Add a database:** New → **Database → PostgreSQL**.
4. On the app service, set **Variables**:
   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference the Postgres service) |
   | `ADMIN_ACCESS_CODE` | a strong shared code you give organizers |
   | `SECRET_KEY` | a long random string |
   | `FRONTEND_URL` | the app's own public https URL (Railway gives you one) |
5. Deploy. Open the public URL. Click **Admin login**, enter your name + the code,
   then **Import CSV** → **Rebuild men** → **Rebuild women**.

`healthcheckPath` is `/api/health` (see `railway.json`). Schema is created on boot.

---

## Importing entries

Admin → **Import CSV**. The parser matches on header names (case/space/typo
tolerant) and expects: `Timestamp, Name, Gender, Phone Number, Registration
Number, Year of Study, Level of Experience`. Category comes from **Gender**
(Male → men, Female → women). Re-importing the same file changes nothing.

After importing, click **Rebuild men (A–D)** and **Rebuild women**. `sample_data/`
holds a FAKE sample used by tests and demos; the real entrant file (with phone
numbers) is git-ignored and never committed.

---

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest      # 65 tests; SQLite, no Postgres needed
```
Covers phone normalization, dedup/validation/idempotency, the draw engine for
`N ∈ {2,3,5,6,7,8,13,16,17,31,32}` (correct bracket size/byes, no bye-vs-bye,
every player placed once, valid advancement), and format-driven scoring, RET,
and safe re-advancement.
