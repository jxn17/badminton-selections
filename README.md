# College Badminton Team Selection — Draws & Scoring

A BWF-style single-elimination draw and live-scoring system for college team
selection. Two independent tournaments run in parallel — **Men's** and
**Women's**. Public pages are read-only and need no login; admins sign in with
Google to import entries, generate/lock draws, and enter scores directly on the
bracket cards.

- **Frontend:** React 18 + TypeScript + Tailwind + Vite
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2
- **Database:** PostgreSQL (via Docker or a managed `DATABASE_URL`)
- **Admin auth:** Google OAuth with an email whitelist

```
.
├── backend/         FastAPI app, models, draw engine, scoring, tests
├── frontend/        React SPA (public bracket + admin console)
├── sample_data/     entries_sample.csv + its generator
├── docker-compose.yml
└── README.md
```

---

## Quick start (Docker)

Spins up Postgres + the API. The frontend runs separately with Vite (below).

```bash
# from repo root
docker compose up --build
```

The API comes up on <http://localhost:8000> (health check at `/api/health`) and
runs Alembic migrations on boot. Set admin/OAuth env vars first (see below) —
e.g. `ADMIN_EMAILS=you@gmail.com docker compose up`.

Then start the frontend:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api -> :8000)
```

---

## Local start (no Docker)

### 1. Postgres

Either run just the DB from compose:

```bash
docker compose up db
```

…or point `DATABASE_URL` at any Postgres you already have.

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     (or use .venv/Scripts/python.exe directly)
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then edit values
alembic upgrade head        # create the schema
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

---

## Environment variables

Set these for the backend (via `.env`, or the shell / compose environment):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL, e.g. `postgresql+psycopg2://badminton:badminton@localhost:5432/badminton`. Point at a managed instance in production. |
| `ADMIN_EMAILS` | Comma-separated Google emails seeded into the admin whitelist on boot (bootstraps the first admins). |
| `SECRET_KEY` | Signs the admin session cookie — use a long random string. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 2.0 Web client from the [Google Cloud console](https://console.cloud.google.com/apis/credentials). |
| `OAUTH_REDIRECT_URI` | Must match the console config, e.g. `http://localhost:8000/api/auth/callback`. |
| `FRONTEND_URL` | Frontend origin for CORS + post-login redirect (`http://localhost:5173`). |
| `ALLOW_DEV_LOGIN` | **Dev only.** `true` enables `/api/auth/dev-login`, which signs in as the first `ADMIN_EMAILS` entry without Google. Keep `false` in production. |

### Setting up Google OAuth

1. In Google Cloud → *APIs & Services → Credentials*, create an **OAuth client
   ID** of type *Web application*.
2. Add an authorized redirect URI matching `OAUTH_REDIRECT_URI`
   (e.g. `http://localhost:8000/api/auth/callback`).
3. Put the client id/secret into the backend env.
4. Add your Google address to `ADMIN_EMAILS`. Only whitelisted emails can reach
   any mutating endpoint — enforced server-side, never trusting the frontend.

---

## Importing entries from the Google Form

Entries come from a Google Form → Sheet. Export the sheet to CSV, then upload it
on the **Admin → Import entries** page (or `POST /api/admin/import`).

The parser matches on **header names** (case/whitespace tolerant), not column
order, and expects: `Timestamp`, `Full Name`, `College Branch`, `Email`,
`Phone Number`, `Played States or Nationals`, `Applying For`
(`Men's Team` / `Women's Team`).

The pipeline is **idempotent** — re-importing the same file changes nothing:

1. Every field is trimmed.
2. Rows with no name, no phone, or an unrecognized `Applying For` are collected
   into a **skipped** report (never crash).
3. Phone is normalized for dedup: digits only, drop a leading `+91`/`91`/`0`,
   keep the last 10 digits. Both raw and normalized are stored.
4. Deduplicated by normalized phone **per category** (men/women independent);
   on a collision the **earliest `Timestamp`** wins and the drop is logged.
5. Upsert keyed on normalized phone, returning
   `{ imported, duplicates_dropped, skipped_invalid, per_category_counts }`.

A ready sample lives at [`sample_data/entries_sample.csv`](sample_data/entries_sample.csv)
(~36 men, ~29 women, plus deliberate duplicates in mixed formats, `+91`/leading-`0`
numbers, a missing phone, an unrecognized category, and trailing-whitespace rows).
Regenerate it with `python sample_data/generate_sample.py`.

### Seed a demo database

```bash
cd backend
python seed.py                # import sample + generate both draws
python seed.py --with-scores  # also play a few Round-1 results
```

---

## Generating & locking a draw

From **Admin → Generate & lock the draw** (or `POST /api/admin/{category}/draw`):

- `N` players → bracket size `P` = smallest power of two ≥ `N`, with `B = P − N`
  byes. Because `P` is the *smallest* such power, `B < P/2`, so **no bye is ever
  paired against another bye** (proven in code + tests).
- Players are shuffled with **Fisher–Yates** using a stored RNG **seed** — same
  seed + same players reproduces the exact draw (auditable). You can supply a
  seed or let one be generated and recorded.
- Byes are placed on the standard top-seed slot positions so they spread evenly;
  which players sit next to a bye is decided purely by the shuffle.
- The full bracket (Round 1 → Final) is created and wired for advancement; bye
  winners advance immediately.

**Regenerate** is allowed only while the tournament is `draft`. **Lock** freezes
the structure (you're warned first); after locking, only scores/winners change.

---

## Scoring (format-driven — nothing is hardcoded)

Scoring rules come from the editable **Scoring Settings** panel, stored per
tournament as a default (applies to all rounds) plus optional per-round
overrides. Each format sets `points_to_win`, `win_by_two`, `hard_cap`, and
`games_to_win_match` (1 = single game; higher supports best-of-N). Default:
single game to **15**, win-by-two, no cap.

On the bracket, an admin types scores straight into the game column(s) on each
card. The server validates against the resolved format (rejects a sub-target
winning score, enforces win-by-two / hard cap, flags impossible scores inline),
sets the winner, and advances them live into the next match. A player can be
flagged **RET** (opponent advances regardless, partial score preserved). Editing
a decided match correctly withdraws and re-pushes the winner; if the next match
has already started, the edit is blocked with a clear message (reset that match
first). Every score edit, winner change and RET writes to the **audit log**.

Public visitors see the same cards read-only — and **never** any email or phone.

---

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest      # Windows
# or:  pytest
```

Covers phone normalization, dedup/validation, import idempotency, and the draw
engine for `N ∈ {2,3,5,6,7,8,13,16,17,31,32}` (correct `P`/`B`, no bye-vs-bye,
every player placed once, valid advancement chaining), plus format-driven
scoring, advancement, RET, and safe re-advancement. The tests use SQLite, so no
Postgres is needed to run them.

---

## API surface (summary)

Public (no auth): `GET /api/categories/{men|women}/bracket`,
`GET /api/categories/{cat}/players`, `GET /api/health`, `GET /api/auth/me`.

Admin (session required): `POST /api/admin/import`,
`POST /api/admin/{cat}/draw`, `POST /api/admin/{cat}/lock`,
`PUT /api/admin/{cat}/matches/{id}/score`,
`POST|DELETE /api/admin/{cat}/matches/{id}/retire`,
`POST /api/admin/{cat}/matches/{id}/reset`,
`GET|PUT /api/admin/{cat}/formats`, `DELETE /api/admin/{cat}/formats/{round}`,
`GET|POST /api/admin/admins`, `DELETE /api/admin/admins/{id}`,
`GET /api/admin/audit`.
