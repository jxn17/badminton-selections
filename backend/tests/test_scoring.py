"""Scoring, advancement, RET and safe re-advancement tests."""
from __future__ import annotations

import pytest

from sqlalchemy import select

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
    clear_no_show,
    evaluate_game,
    resolve_format,
    set_no_show,
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
        # The only rule: more points wins. The format columns are varied here on
        # purpose to show they no longer change the outcome.
        (15, 10, 15, True, None, "a"),
        (10, 15, 15, True, None, "b"),
        (15, 14, 15, True, None, "a"),    # one ahead is still ahead (was "deuce")
        (17, 15, 15, True, None, "a"),
        (16, 15, 15, True, None, "a"),
        (20, 15, 15, True, None, "a"),    # margin > 2 in "deuce" — fine now
        (11, 5, 11, False, None, "a"),
        (12, 5, 11, False, None, "a"),    # past the target — fine now
        (10, 8, 15, True, None, "a"),     # short game, nobody near 15 — still a win
        (21, 20, 15, True, 21, "a"),
        (22, 20, 15, True, 21, "a"),      # past the cap — fine now
        (3, 1, 21, True, 30, "a"),        # a heavily shortened game still counts
        (15, 15, 15, True, None, "incomplete"),  # level: nothing to decide
        (0, 0, 21, True, 30, "incomplete"),      # untouched row
    ],
)
def test_evaluate_game_is_just_whoever_scored_more(a, b, ptw, wbt, cap, expected):
    assert evaluate_game(fmt(ptw, wbt, cap), a, b).status == expected


def test_negative_scores_are_still_rejected():
    """The one thing that can't be a real scoreline."""
    assert evaluate_game(fmt(), -1, 5).status == "invalid"
    assert evaluate_game(fmt(), 5, -2).status == "invalid"


@pytest.mark.parametrize("ptw,cap,wbt", [(11, 11, True), (15, None, False), (21, 30, True)])
def test_format_no_longer_constrains_the_result(ptw, cap, wbt):
    """Same scoreline, wildly different formats, same verdict every time."""
    f = fmt(ptw=ptw, wbt=wbt, cap=cap)
    assert evaluate_game(f, 9, 4).status == "a"
    assert evaluate_game(f, 4, 9).status == "b"
    assert evaluate_game(f, 7, 7).status == "incomplete"


async def _setup(db, n=8, seed=1):
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
    await db.flush()
    db.add(RoundFormat(tournament_id=t.id, round_number=None, points_to_win=15,
                       win_by_two=True, hard_cap=None, games_to_win_match=1))
    await db.flush()
    await generate_draw(db, t, seed=seed)
    await db.commit()
    return t


async def _round(db, t, r):
    return (
        (
            await db.execute(
                select(Match)
                .where(Match.tournament_id == t.id, Match.round_number == r)
                .order_by(Match.position_in_round)
            )
        )
        .scalars()
        .all()
    )


async def test_resolve_format_prefers_override(db):
    t = await _setup(db)
    db.add(RoundFormat(tournament_id=t.id, round_number=1, points_to_win=11,
                       win_by_two=False, hard_cap=None, games_to_win_match=1))
    await db.commit()
    assert (await resolve_format(db, t, 1)).points_to_win == 11   # override
    assert (await resolve_format(db, t, 2)).points_to_win == 15   # default


async def test_score_advances_winner(db):
    t = await _setup(db, n=8, seed=3)  # 8 players, no byes -> clean Round 1
    r1 = await _round(db, t, 1)
    m = next(m for m in r1 if not m.is_bye)
    winner_id = m.player_a_id

    await apply_scores(db, m, [GameInput(1, 15, 9)], "admin@test.dev")
    await db.commit()

    assert m.status == MatchStatus.completed
    assert m.winner_id == winner_id
    nxt = await db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced == winner_id


async def test_unusual_scorelines_are_accepted_and_advance_the_leader(db):
    """Scorelines the old target/win-by-two/cap rules rejected now just work.

    The format here is a 15-point game, and none of these fit it — that's the
    point: the organiser's number is the result.
    """
    t = await _setup(db, n=8, seed=3)
    for game in (GameInput(1, 20, 15), GameInput(1, 3, 1), GameInput(1, 40, 2)):
        m = next(m for m in await _round(db, t, 1) if not m.is_bye)
        winner = m.player_a_id
        await apply_scores(db, m, [game], "admin@test.dev")
        await db.commit()
        assert m.status == MatchStatus.completed
        assert m.winner_id == winner
        nxt = await db.get(Match, m.next_match_id)
        advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
        assert advanced == winner


async def test_level_score_leaves_the_match_undecided(db):
    """Nobody is ahead, so nobody advances."""
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    await apply_scores(db, m, [GameInput(1, 12, 12)], "admin@test.dev")
    await db.commit()
    assert m.winner_id is None
    assert m.status == MatchStatus.in_progress
    nxt = await db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced is None


async def test_negative_score_is_rejected(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    with pytest.raises(ScoringError):
        await apply_scores(db, m, [GameInput(1, -5, 15)], "admin@test.dev")


async def test_retirement_advances_opponent(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    retiree = m.player_a_id
    opponent = m.player_b_id

    # A partial score is entered, then A retires.
    await apply_scores(db, m, [GameInput(1, 5, 8)], "admin@test.dev")
    await set_retirement(db, m, retiree, "admin@test.dev")
    await db.commit()

    assert m.winner_id == opponent
    assert m.retired_player_id == retiree
    assert m.status == MatchStatus.completed
    assert len(m.games) == 1  # partial score preserved
    nxt = await db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced == opponent


async def test_reedit_readvances_when_downstream_not_started(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    a, b = m.player_a_id, m.player_b_id

    await apply_scores(db, m, [GameInput(1, 15, 9)], "admin@test.dev")  # A wins
    await db.commit()
    nxt = await db.get(Match, m.next_match_id)
    slot_is_a = m.position_in_round % 2 == 0
    assert (nxt.player_a_id if slot_is_a else nxt.player_b_id) == a

    # Correct the result so B wins; downstream hasn't started -> silent re-advance.
    await apply_scores(db, m, [GameInput(1, 9, 15)], "admin@test.dev")
    await db.commit()
    assert m.winner_id == b
    assert (nxt.player_a_id if slot_is_a else nxt.player_b_id) == b


async def test_reedit_blocked_when_downstream_started(db):
    t = await _setup(db, n=8, seed=3)
    r1 = await _round(db, t, 1)
    # Find two Round-1 matches that feed the same Round-2 match.
    m0 = next(m for m in r1 if not m.is_bye)
    sibling = next(
        m for m in r1 if m.next_match_id == m0.next_match_id and m.id != m0.id
    )
    await apply_scores(db, m0, [GameInput(1, 15, 9)], "admin@test.dev")
    await apply_scores(db, sibling, [GameInput(1, 15, 9)], "admin@test.dev")
    await db.commit()

    # Now the Round-2 match has both players; start it.
    nxt = await db.get(Match, m0.next_match_id)
    await apply_scores(db, nxt, [GameInput(1, 15, 12)], "admin@test.dev")
    await db.commit()

    # Re-editing m0 to flip its winner must be blocked.
    with pytest.raises(ScoringError):
        await apply_scores(db, m0, [GameInput(1, 9, 15)], "admin@test.dev")


# --------------------------------------------------------------------------
# No-show: distinct from RET — the match never started, so no partial score
# is kept, and the opponent wins immediately.
# --------------------------------------------------------------------------
async def test_no_show_advances_opponent_with_no_games(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    absent = m.player_a_id
    opponent = m.player_b_id

    await set_no_show(db, m, absent, "admin@test.dev")
    await db.commit()

    assert m.winner_id == opponent
    assert m.no_show_player_id == absent
    assert m.retired_player_id is None
    assert m.status == MatchStatus.completed
    assert len(m.games) == 0  # no-show keeps no partial score (unlike RET)
    nxt = await db.get(Match, m.next_match_id)
    advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert advanced == opponent


async def test_no_show_discards_any_partial_score_already_entered(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    absent = m.player_a_id

    await apply_scores(db, m, [GameInput(1, 8, 6)], "admin@test.dev")
    await db.commit()
    assert len(m.games) == 1

    await set_no_show(db, m, absent, "admin@test.dev")
    await db.commit()
    assert len(m.games) == 0  # no-show clears it, unlike RET which preserves it


async def test_no_show_and_retire_are_mutually_exclusive(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    a, b = m.player_a_id, m.player_b_id

    await set_retirement(db, m, a, "admin@test.dev")
    assert m.retired_player_id == a
    await set_no_show(db, m, b, "admin@test.dev")
    assert m.no_show_player_id == b
    assert m.retired_player_id is None  # setting no-show clears a prior RET
    assert m.winner_id == a  # b (no-show) loses, a wins


async def test_clear_no_show_returns_to_pending(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    absent = m.player_a_id

    await set_no_show(db, m, absent, "admin@test.dev")
    await db.commit()
    await clear_no_show(db, m, "admin@test.dev")
    await db.commit()

    assert m.no_show_player_id is None
    assert m.winner_id is None
    assert m.status == MatchStatus.pending


async def test_no_show_blocked_on_bye(db):
    t = await _setup(db, n=7, seed=3)  # odd count guarantees at least one bye
    m = next(m for m in await _round(db, t, 1) if m.is_bye)
    real_player = m.player_a_id if m.player_a_id is not None else m.player_b_id
    with pytest.raises(ScoringError):
        await set_no_show(db, m, real_player, "admin@test.dev")


async def test_no_show_rejects_player_not_in_match(db):
    t = await _setup(db, n=8, seed=3)
    matches = await _round(db, t, 1)
    m = next(m for m in matches if not m.is_bye)
    other = next(m2 for m2 in matches if m2.id != m.id and not m2.is_bye)
    stranger = other.player_a_id
    with pytest.raises(ScoringError):
        await set_no_show(db, m, stranger, "admin@test.dev")


async def test_no_show_blocked_when_downstream_started(db):
    t = await _setup(db, n=8, seed=3)
    r1 = await _round(db, t, 1)
    m0 = next(m for m in r1 if not m.is_bye)
    sibling = next(m for m in r1 if m.next_match_id == m0.next_match_id and m.id != m0.id)
    await apply_scores(db, m0, [GameInput(1, 15, 9)], "admin@test.dev")
    await apply_scores(db, sibling, [GameInput(1, 15, 9)], "admin@test.dev")
    await db.commit()
    nxt = await db.get(Match, m0.next_match_id)
    await apply_scores(db, nxt, [GameInput(1, 15, 12)], "admin@test.dev")
    await db.commit()

    # m0's winner already advanced into a started match; marking THAT winner as
    # a no-show would flip the result, which must be blocked, same guard as a
    # score re-edit that changes the winner.
    with pytest.raises(ScoringError):
        await set_no_show(db, m0, m0.winner_id, "admin@test.dev")
