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
WOMEN_ENTRIES = os.path.join(
    os.path.dirname(__file__), "..", "women_entries",
    "Badminton Trials 2026 (Responses) - Womens.csv",
)


def _resolve(*candidates: str) -> str | None:
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        totals = {"men": 0, "women": 0}
        base = os.path.dirname(__file__)
        sample_path = _resolve(
            os.path.join(base, "sample_data", "entries_sample.csv"),
            os.path.join(base, "..", "sample_data", "entries_sample.csv"),
        )
        women_path = _resolve(
            os.path.join(base, "women_entries", "Badminton Trials 2026 (Responses) - Womens.csv"),
            os.path.join(base, "..", "women_entries", "Badminton Trials 2026 (Responses) - Womens.csv"),
        )
        if sample_path:
            with open(sample_path, encoding="utf-8") as f:
                report = import_csv(db, f.read())
            for k, v in report.per_category_counts.items():
                totals[k] += v
            print("Sample import:", report.per_category_counts)
        if women_path:
            with open(women_path, encoding="utf-8") as f:
                report = import_csv(db, f.read())
            for k, v in report.per_category_counts.items():
                totals[k] += v
            print("Women entries import:", report.per_category_counts)
        print("Totals:", totals)
        if totals.get("men", 0) > 0:
            print("Men:", rebuild_men(db, seed=2026))
        if totals.get("women", 0) > 0:
            print("Women:", rebuild_women(db, seed=777))
    finally:
        db.close()


if __name__ == "__main__":
    main()
