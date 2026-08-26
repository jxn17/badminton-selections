"""Seed the DB from the FAKE sample CSV and build all draws.

Usage (from backend/, venv active, DATABASE_URL set):
    python seed.py
For the real event, import the real CSV through the admin UI instead.
"""
from __future__ import annotations

import os

from app.csv_import import import_csv
from app.database import Base, SessionLocal, engine
from app.service import rebuild_men, rebuild_women

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_data", "entries_sample.csv")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        with open(SAMPLE, encoding="utf-8") as f:
            report = import_csv(db, f.read())
        print("Import:", report.per_category_counts,
              "| duplicates:", report.duplicates_dropped,
              "| skipped:", report.skipped_invalid)
        print("Men:", rebuild_men(db, seed=2026))
        print("Women:", rebuild_women(db, seed=777))
    finally:
        db.close()


if __name__ == "__main__":
    main()
