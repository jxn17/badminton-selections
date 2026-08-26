"""Scoring, advancement, RET and safe re-advancement tests."""
from __future__ import annotations

import pytest

from app.draw import generate_draw
from app.models import (
    Category,
    Match,
    MatchStatus,
    Player,
    RoundFormat,
    Tournament,
    TournamentStatus,
)
from app.scoring import (
    GameInput,
    ScoringError,
    apply_scores,
    evaluate_game,
    resolve_format,
    set_retirement,
)


def fmt(ptw=15, wbt=True, cap=None, games=1):
    return RoundFormat(
        tournament_id=0, round_number=None, points_to_win=ptw,
        win_by_two=wbt, hard_cap=cap, games_to_win_match=games,
    )


@pytest.mark.parametrize(
    "a,b,ptw,wbt,cap,expected",
    [
        (15, 10, 15, True, None, "a"),
        (10, 15, 15, True, None, "b"),
        (15, 14, 15, True, None, "incomplete"),  # deuce continues
        (17, 15, 15, True, None, "a"),           # won by two in deuce
        (16, 15, 15, True, None, "incomplete"),  # 1-point lead in deuce
        (20, 15, 15, True, None, "invalid"),     # can't win by >2 in deuce
        (11, 5, 11, False, None, "a"),           # no win-by-two
        (12, 5, 11, False, None, "invalid"),     # can't exceed target
        (10, 8, 15, True, None, "incomplete"),   # live, nobody at target
        (21, 20, 15, True, 21, "a"),             # hard cap ends it
        (22, 20, 15, True, 21, "invalid"),       # over the cap
        (15, 15, 15, True, None, "invalid"),     # tie can't both reach target
    ],
)
def test_evaluate_game(a, b, ptw, wbt, cap, expected):
    assert evaluate_game(fmt(ptw, wbt, cap), a, b).status == expected


def _setup(db, n=8, seed=1):
    for i in range(n):
        db.add(
            Player(
                full_name=f"P{i}", phone_raw=str(9000000000 + i),
                phone_normalized=str(9000000000 + i), dedup_key=f"ph:{9000000000 + i}",
                category=Category.men,
            )
        )
    t = Tournament(category=Category.men, status=TournamentStatus.draft)
    db.add(t)
    db.flush()
    db.add(RoundFormat(tournament_id=t.id, round_number=None, points_to_win=15,
                       win_by_two=True, hard_cap=None, games_to_win_match=1))
    db.flush()
    generate_draw(db, t, seed=seed)
    db.commit()
    return t


def _round(db, t, r):
    return (
        db.query(Match)
        .filter(Match.tournament_id == t.id, Match.round_number == r)
        .order_by(Match.position_in_round)
        .all()
    )


def test_resolve_format_prefers_override(db):
    t = _setup(db)
    db.add(RoundFormat(tournament_id=t.id, round_number=1, points_to_win=11,
                       win_by_two=False, hard_cap=None, games_to_win_match=1))
    db.commit()
    assert resolve_format(db, t, 1).points_to_win == 11   # override
    assert resolve_format(db, t, 2).points_to_win == 15   # default


def test_score_advances_winner(db):
    t = _setup(db, n=8, seed=3)  # 8 players, no byes -> clean Round 1
    r1 = _round(db, t, 1)
    m = next(m for m in r1 if not m.is_bye)
    winner_id = m.player_a_id

    apply_scores(db, m, [GameInput(1, 15, 9)], "admin@test.dev")
    db.commit()

    assert m.status == MatchStatus.completed
    assert m.winner_id == winner_id
    nxt = db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced == winner_id


def test_invalid_score_raises(db):
    t = _setup(db, n=8, seed=3)
    m = next(m for m in _round(db, t, 1) if not m.is_bye)
    with pytest.raises(ScoringError):
        apply_scores(db, m, [GameInput(1, 20, 15)], "admin@test.dev")  # >2 in deuce


def test_retirement_advances_opponent(db):
    t = _setup(db, n=8, seed=3)
    m = next(m for m in _round(db, t, 1) if not m.is_bye)
    retiree = m.player_a_id
    opponent = m.player_b_id

    # A partial score is entered, then A retires.
    apply_scores(db, m, [GameInput(1, 5, 8)], "admin@test.dev")
    set_retirement(db, m, retiree, "admin@test.dev")
    db.commit()

    assert m.winner_id == opponent
    assert m.retired_player_id == retiree
    assert m.status == MatchStatus.completed
    assert len(m.games) == 1  # partial score preserved
    nxt = db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced == opponent


def test_reedit_readvances_when_downstream_not_started(db):
    t = _setup(db, n=8, seed=3)
    m = next(m for m in _round(db, t, 1) if not m.is_bye)
    a, b = m.player_a_id, m.player_b_id

    apply_scores(db, m, [GameInput(1, 15, 9)], "admin@test.dev")  # A wins
    db.commit()
    nxt = db.get(Match, m.next_match_id)
    slot_is_a = m.position_in_round % 2 == 0
    assert (nxt.player_a_id if slot_is_a else nxt.player_b_id) == a

    # Correct the result so B wins; downstream hasn't started -> silent re-advance.
    apply_scores(db, m, [GameInput(1, 9, 15)], "admin@test.dev")
    db.commit()
    assert m.winner_id == b
    assert (nxt.player_a_id if slot_is_a else nxt.player_b_id) == b


def test_reedit_blocked_when_downstream_started(db):
    t = _setup(db, n=8, seed=3)
    r1 = _round(db, t, 1)
    # Find two Round-1 matches that feed the same Round-2 match.
    m0 = next(m for m in r1 if not m.is_bye)
    sibling = next(
        m for m in r1 if m.next_match_id == m0.next_match_id and m.id != m0.id
    )
    apply_scores(db, m0, [GameInput(1, 15, 9)], "admin@test.dev")
    apply_scores(db, sibling, [GameInput(1, 15, 9)], "admin@test.dev")
    db.commit()

    # Now the Round-2 match has both players; start it.
    nxt = db.get(Match, m0.next_match_id)
    apply_scores(db, nxt, [GameInput(1, 15, 12)], "admin@test.dev")
    db.commit()

    # Re-editing m0 to flip its winner must be blocked.
    with pytest.raises(ScoringError):
        apply_scores(db, m0, [GameInput(1, 9, 15)], "admin@test.dev")
