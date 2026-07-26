"""Seed the DB from the sample CSV and generate both draws.

Usage (from backend/, with the venv active and DATABASE_URL pointing at your DB):
    python seed.py
Optionally also plays a few random results for a livelier demo:
    python seed.py --with-scores
"""
from __future__ import annotations

import os
import sys

from app.database import Base, SessionLocal, engine
from app.draw import generate_draw
from app.csv_import import import_csv
from app.models import Category, Match, MatchStatus, RoundFormat, Tournament, TournamentStatus
from app.scoring import GameInput, apply_scores

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_data", "entries_sample.csv")


def get_or_create_tournament(db, cat: Category) -> Tournament:
    t = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    if t is None:
        t = Tournament(category=cat, status=TournamentStatus.draft)
        db.add(t)
        db.flush()
        db.add(RoundFormat(tournament_id=t.id, round_number=None, points_to_win=15,
                           win_by_two=True, hard_cap=None, games_to_win_match=1))
        db.flush()
    return t


def play_some(db, t: Tournament) -> None:
    """Fill in a few Round-1 results so the bracket isn't all empty."""
    import random

    rng = random.Random(t.draw_seed or 1)
    r1 = (
        db.query(Match)
        .filter(Match.tournament_id == t.id, Match.round_number == 1, Match.is_bye == False)  # noqa: E712
        .order_by(Match.position_in_round)
        .all()
    )
    for m in r1[: max(1, len(r1) // 2)]:
        if m.player_a_id and m.player_b_id:
            if rng.random() < 0.5:
                apply_scores(db, m, [GameInput(1, 15, rng.randint(5, 13))], "seed@demo")
            else:
                apply_scores(db, m, [GameInput(1, rng.randint(5, 13), 15)], "seed@demo")
    db.commit()


def main() -> None:
    with_scores = "--with-scores" in sys.argv
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        with open(SAMPLE, encoding="utf-8") as f:
            report = import_csv(db, f.read())
        print("Import:", report.as_dict()["per_category_counts"],
              "| duplicates:", report.duplicates_dropped,
              "| skipped:", report.skipped_invalid)

        for cat in (Category.men, Category.women):
            t = get_or_create_tournament(db, cat)
            if t.status != TournamentStatus.draft:
                print(f"{cat.value}: locked, skipping redraw")
                continue
            generate_draw(db, t, seed=1000 + (0 if cat == Category.men else 1))
            db.commit()
            print(f"{cat.value}: bracket_size={t.bracket_size} byes={t.num_byes} seed={t.draw_seed}")
            if with_scores:
                play_some(db, t)
                print(f"{cat.value}: played some Round 1 results")
    finally:
        db.close()


if __name__ == "__main__":
    main()
