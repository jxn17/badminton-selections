"""Wipe all entries/draws and re-import real women's CSV only.

Usage (from backend/, DATABASE_URL set):
    python reset_women.py
"""
from __future__ import annotations

import os

from sqlalchemy import text

from app.csv_import import import_csv
from app.database import SessionLocal, engine
from app.service import rebuild_women

WOMEN_ENTRIES = os.path.join(
    os.path.dirname(__file__), "women_entries",
    "Badminton Trials 2026 (Responses) - Womens.csv",
)
if not os.path.isfile(WOMEN_ENTRIES):
    WOMEN_ENTRIES = os.path.join(
        os.path.dirname(__file__), "..", "women_entries",
        "Badminton Trials 2026 (Responses) - Womens.csv",
    )


def main() -> None:
    if not os.path.isfile(WOMEN_ENTRIES):
        raise SystemExit(f"Women's CSV not found: {WOMEN_ENTRIES}")

    with engine.connect() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE games, matches, round_formats, tournaments, audit_log, players "
                "RESTART IDENTITY CASCADE"
            )
        )
        conn.commit()
    print("Cleared all players and draws.")

    db = SessionLocal()
    try:
        with open(WOMEN_ENTRIES, encoding="utf-8") as f:
            report = import_csv(db, f.read())
        print("Import:", report.per_category_counts,
              "| duplicates:", report.duplicates_dropped,
              "| skipped:", report.skipped_invalid)
        print("Women:", rebuild_women(db, seed=777))
    finally:
        db.close()


if __name__ == "__main__":
    main()
