# Badminton Trials 2026 — Draws & Scoring

Selection-trial draw and live-scoring tool. Entrants come from a Google Form
(category is taken from the **Gender** field). Men are split into **four balanced
groups (A–D)**, women run as a single **128-draw**. Public pages are read-only;
admins sign in with a **shared access code** to import, build draws, enter scores,
schedule matches, flag shortlist players, swap players, and add walk-ins.

- **Frontend:** React 18 + TypeScript + Tailwind + Vite
- **Backend:** FastAPI + SQLAlchemy 2 (fully async) + Pydantic v2
- **Database:** PostgreSQL over **asyncpg** (SQLite/aiosqlite for tests)
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
- **Strike a player off (admin only):** the ✗ on a match card (or **Strike** in the
  search) crosses a name out in red. It's a marker on the *person*, not on a match,
  so it works whoever they're up against — a real opponent, a bye, or a slot still
  showing TBD — and it never advances anyone. Use no-show or a score when a result
  should actually move someone through.
- **Edit any entry (admin only):** search a name → **Edit** to fix a misspelt name,
  a wrong phone, a missing registration number, year, or level of experience. Entries
  come off a Google Form filled in by hundreds of students, so corrections are routine.
  Identity moves with the correction, so a later re-import still recognises the same
  person rather than adding them twice; clashing details are refused by name. Category
  and group aren't editable here — they decide which draw someone is in, so those stay
  with **Move to group** / rebuild, which redraw the bracket properly.
- **Find a player, land on their tie:** search a name and click either the name or
  one of their listed matches — the app switches to that group, scrolls the tie into
  view, rings the card and highlights the player inside it. On phones it also flips
  to the round the tie is in.
- **Phone numbers** show to signed-in admins only — never on the public page.
- **Multi-admin:** the shared code lets several organizers edit at once; the bracket
  auto-refreshes every 15s so they see each other's updates. Each admin enters a
  name that's recorded in the audit log with every change.

---

## Performance notes

**Everything is async, end to end.** Routes, the service/scoring/draw layer and the
SQLAlchemy session all run on `AsyncSession` over an asyncio driver, so a slow
query stalls only its own request instead of blocking the event loop for every
concurrent visitor. Two consequences worth knowing when editing the code:

- Relationships never lazy-load on plain attribute access. `Match.games` and
  `Match.tournament` are eager-loaded (`lazy="selectin"`, one batched query per
  result set); anything else is fetched with an explicit `selectinload(...)` or
  `await obj.awaitable_attrs.<name>`.
- Sessions use `expire_on_commit=False`, so an object returned after `commit()` is
  still readable. In exchange, code that replaces a collection must go through the
  relationship (`match.games.clear()`), not bare `db.delete(...)`, or the in-memory
  copy goes stale.

**The public pages are cached in memory.** Every anonymous visitor to a draw gets
byte-identical data, so `/api/groups` and `/api/bracket` are served from a
process-local TTL cache (`PUBLIC_CACHE_TTL`, default 45s) holding the already-built
Pydantic response — a hit never touches the database. It stays honest during a live
event because:

- **any admin write clears the cache**, so the TTL only ever delays *unchanged*
  data; a score entered now is public on the very next request; and
- **admins are never served from it** — their responses carry phone numbers and the
  shortlist flag, so only the PII-free copy is cached and only a request without an
  admin session can read it.

`GET /api/cache-stats` reports live entry count, TTL and version.

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
DATABASE_URL=sqlite+aiosqlite:///./trials.db ADMIN_ACCESS_CODE=trials2026 SECRET_KEY=dev \
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
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference the Postgres service — the provider's `postgres://…` spelling is normalized to asyncpg automatically, `?sslmode=` included) |
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
.venv/Scripts/python.exe -m pytest      # 154 tests; SQLite, no Postgres needed
```
Covers phone normalization, dedup/validation/idempotency, the draw engine for
`N ∈ {2,3,5,6,7,8,13,16,17,31,32}` (correct bracket size/byes, no bye-vs-bye,
every player placed once, valid advancement), format-driven scoring, RET, no-show
and safe re-advancement, the roster/scheduling service functions (walk-ins,
withdrawals, swaps, group moves, day and paste-to-schedule), `DATABASE_URL`
normalization, and an end-to-end HTTP pass over the real ASGI app that pins down
the async request path and the cache's behaviour (what it serves, to whom, and
what clears it).
