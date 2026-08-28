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


# --------------------------------------------------------------------------
# Golden point / sudden death: hard_cap == points_to_win means the game ends
# the instant either side reaches the target, no matter the margin — i.e. at
# parity one below the target (14-14 for a 15-point game, 10-10 for 11-point),
# the very next point decides it. This is the *existing* generic evaluate_game
# logic; these tests pin down that the trick actually produces "golden point"
# behaviour for the specific formats the user asked to support.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ptw,a,b,expected",
    [
        # 11-point game, golden point (cap == 11)
        (11, 10, 10, "incomplete"),  # parity one below target -> not decided yet
        (11, 11, 10, "a"),           # next point wins outright, no 2-point margin needed
        (11, 10, 11, "b"),
        (11, 12, 10, "invalid"),     # game must have ended at 11-10; can't reach 12
        (11, 9, 8, "incomplete"),    # ordinary live rally, nobody at target
        # 15-point game, golden point (cap == 15)
        (15, 14, 14, "incomplete"),
        (15, 15, 14, "a"),
        (15, 14, 15, "b"),
        (15, 16, 14, "invalid"),
        # 21-point game, golden point (cap == 21) — same trick at badminton's usual length
        (21, 20, 20, "incomplete"),
        (21, 21, 20, "a"),
        (21, 22, 20, "invalid"),
    ],
)
def test_golden_point(ptw, a, b, expected):
    golden = fmt(ptw=ptw, wbt=True, cap=ptw)  # hard_cap == points_to_win => golden point
    assert evaluate_game(golden, a, b).status == expected


def test_golden_point_does_not_affect_normal_leads():
    """A side that's already 2+ ahead at the target still wins normally under
    golden point — the rule only changes what happens exactly AT parity."""
    golden = fmt(ptw=15, wbt=True, cap=15)
    assert evaluate_game(golden, 15, 10).status == "a"
    assert evaluate_game(golden, 15, 13).status == "a"


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


async def test_invalid_score_raises(db):
    t = await _setup(db, n=8, seed=3)
    m = next(m for m in await _round(db, t, 1) if not m.is_bye)
    with pytest.raises(ScoringError):
        await apply_scores(db, m, [GameInput(1, 20, 15)], "admin@test.dev")  # >2 in deuce


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
