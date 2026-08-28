"""Roster and scheduling operations.

These are the orchestration functions the admin toolbar drives — walk-ins,
withdrawals, swaps, group moves, and the two schedulers. They were previously
exercised only through the UI; each one now runs a real async session, so a
stray blocking attribute access shows up here rather than mid-event.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.csv_import import import_csv
from app.draw import generate_draw
from app.grouping import GROUP_LABELS
from app.models import (
    Category,
    Match,
    MatchStatus,
    Player,
    RoundFormat,
    Tournament,
    TournamentStatus,
)
from app.scoring import GameInput, ScoringError, apply_scores
from app.service import (
    _fmt_hhmm,
    _parse_hhmm,
    add_walkin,
    clear_schedule,
    find_tournament,
    move_players_to_groups,
    rebuild_men,
    rebuild_women,
    remove_player,
    schedule_day,
    schedule_specific_players,
    swap_players,
)

HEADER = (
    "Timestamp,Name,Gender,Phone Number,Registration Number,"
    "Year of Study (4th years not allowed),Level of Exprience"
)
LEVELS = ["Nationals", "District", "School", "Casual", "Beginner"]


def _entries(n_men: int = 16, n_women: int = 8) -> str:
    rows = [HEADER]
    for i in range(n_men):
        rows.append(
            f"27/07/2026 10:00:00,Man {i},Male,90000000{i:02d},"
            f"2610900500{i:02d},1st Year,{LEVELS[i % len(LEVELS)]}"
        )
    for i in range(n_women):
        rows.append(
            f"27/07/2026 11:00:00,Woman {i},Female,80000000{i:02d},"
            f"2610900600{i:02d},1st Year,{LEVELS[i % len(LEVELS)]}"
        )
    return "\n".join(rows) + "\n"


@pytest.fixture()
async def drawn(db):
    await import_csv(db, _entries())
    await rebuild_men(db, seed=2026)
    await rebuild_women(db, seed=777)
    await db.commit()
    return db


async def _matches(db, t, round_number=None):
    q = select(Match).where(Match.tournament_id == t.id)
    if round_number is not None:
        q = q.where(Match.round_number == round_number)
    return (await db.execute(q.order_by(Match.position_in_round))).scalars().all()


async def _player(db, name):
    return (
        await db.execute(select(Player).where(Player.full_name == name))
    ).scalar_one()


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,minutes", [("09:00", 540), ("17:30", 1050), (" 7:05 ", 425), ("00:00", 0)]
)
def test_parse_hhmm(text, minutes):
    assert _parse_hhmm(text) == minutes


@pytest.mark.parametrize("bad", ["9am", "25:00", "12:60", "", "noon"])
def test_parse_hhmm_rejects_nonsense(bad):
    with pytest.raises(ScoringError):
        _parse_hhmm(bad)


@pytest.mark.parametrize(
    "minutes,text", [(540, "9:00am"), (720, "12:00pm"), (0, "12:00am"), (1035, "5:15pm")]
)
def test_fmt_hhmm(minutes, text):
    assert _fmt_hhmm(minutes) == text


# --------------------------------------------------------------------------
# Draw building
# --------------------------------------------------------------------------
async def test_rebuild_men_fills_four_balanced_groups(drawn):
    db = drawn
    counts = {}
    for label in GROUP_LABELS:
        t = await find_tournament(db, Category.men, label)
        assert t is not None
        counts[label] = len(
            (
                await db.execute(
                    select(Player).where(
                        Player.category == Category.men, Player.group_label == label
                    )
                )
            )
            .scalars()
            .all()
        )
    assert sum(counts.values()) == 16
    # Snake draft: no group may be more than one player larger than another.
    assert max(counts.values()) - min(counts.values()) <= 1


async def test_women_run_as_a_single_ungrouped_draw(drawn):
    t = await find_tournament(drawn, Category.women, None)
    assert t is not None and t.group_label is None
    assert t.bracket_size == 8


# --------------------------------------------------------------------------
# Walk-ins
# --------------------------------------------------------------------------
async def test_walkin_takes_an_open_bye_and_makes_it_a_real_match(db):
    # 12 men -> 3 per group -> a bracket of 4 with one bye, i.e. somewhere for a
    # walk-in to slot into.
    await import_csv(db, _entries(n_men=12, n_women=2))
    await rebuild_men(db, seed=11)
    await db.commit()

    p = await _player(db, "Man 0")
    result = await add_walkin(db, Category.men, "Late Arrival", "9111111111", "Casual", p.group_label)
    await db.commit()

    assert result["group_label"] == p.group_label
    assert result["placed"] is True
    m = await db.get(Match, result["match_id"])
    assert m.is_bye is False
    assert m.winner_id is None
    assert m.status == MatchStatus.pending
    assert result["player_id"] in (m.player_a_id, m.player_b_id)


async def test_walkin_picks_the_smallest_mens_group_when_none_is_given(drawn):
    db = drawn
    result = await add_walkin(db, Category.men, "Auto Placed", "9222222222", "Casual", None)
    await db.commit()
    assert result["group_label"] in GROUP_LABELS
    p = await db.get(Player, result["player_id"])
    assert p.is_walkin is True
    assert p.group_label == result["group_label"]


async def test_walkin_needs_a_name(db):
    with pytest.raises(ScoringError):
        await add_walkin(db, Category.men, "   ", "9333333333", "Casual", None)


# --------------------------------------------------------------------------
# Withdrawals
# --------------------------------------------------------------------------
async def test_remove_player_gives_the_opponent_a_walkover(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    leaving, staying = m.player_a_id, m.player_b_id

    await remove_player(db, leaving)
    await db.commit()

    await db.refresh(m)
    assert m.is_bye is True
    assert m.winner_id == staying
    assert m.status == MatchStatus.completed
    nxt = await db.get(Match, m.next_match_id)
    slot = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
    assert slot == staying
    assert await db.get(Player, leaving) is None


async def test_remove_player_is_blocked_once_they_have_played(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    await apply_scores(db, m, [GameInput(1, 21, 10)], "admin")
    await db.commit()

    with pytest.raises(ScoringError):
        await remove_player(db, m.player_a_id)


# --------------------------------------------------------------------------
# Swaps
# --------------------------------------------------------------------------
async def test_swap_exchanges_two_first_round_positions(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    real = [x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id]
    if len(real) < 2:
        pytest.skip("group A has fewer than two contested first-round matches")
    mx, my = real[0], real[1]
    x, y = mx.player_a_id, my.player_a_id

    await swap_players(db, t, x, y)
    await db.commit()

    assert mx.player_a_id == y
    assert my.player_a_id == x


async def test_swap_refuses_a_played_match(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    real = [x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id]
    if len(real) < 2:
        pytest.skip("group A has fewer than two contested first-round matches")
    await apply_scores(db, real[0], [GameInput(1, 21, 10)], "admin")
    await db.commit()
    with pytest.raises(ScoringError):
        await swap_players(db, t, real[0].player_a_id, real[1].player_a_id)


async def test_swap_needs_two_different_players(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye)
    with pytest.raises(ScoringError):
        await swap_players(db, t, m.player_a_id, m.player_a_id)


# A draw with byes — most of the field sits on one, so swapping bye players is
# the common case, not a corner case.
async def _bye_group(db, n=5, seed=7):
    for i in range(n):
        db.add(
            Player(
                full_name=f"P{i}",
                phone_normalized=str(9000000000 + i),
                dedup_key=f"ph:{9000000000 + i}",
                category=Category.men,
                group_label="A",
            )
        )
    t = Tournament(category=Category.men, group_label="A", status=TournamentStatus.draft)
    db.add(t)
    await db.flush()
    db.add(
        RoundFormat(
            tournament_id=t.id, round_number=None, points_to_win=21,
            win_by_two=True, hard_cap=30, games_to_win_match=1,
        )
    )
    await db.flush()
    await generate_draw(db, t, seed=seed)  # 5 players -> bracket of 8, 3 byes
    await db.commit()
    return t


def _occupant(m: Match) -> int:
    return m.player_a_id if m.player_a_id is not None else m.player_b_id


async def _advanced_into(db, m: Match) -> int | None:
    nxt = await db.get(Match, m.next_match_id)
    return nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id


async def test_swap_two_bye_players_trades_positions_and_advancement(db):
    """The bug fix: two players both sitting on byes can be exchanged, and each
    bye's walkover winner + Round-2 advancement follows them."""
    t = await _bye_group(db)
    byes = [m for m in await _matches(db, t, 1) if m.is_bye]
    assert len(byes) >= 2
    m0, m1 = byes[0], byes[1]
    p0, p1 = _occupant(m0), _occupant(m1)

    await swap_players(db, t, p0, p1)
    await db.commit()

    assert _occupant(m0) == p1 and _occupant(m1) == p0
    assert m0.winner_id == p1 and m1.winner_id == p0
    assert await _advanced_into(db, m0) == p1
    assert await _advanced_into(db, m1) == p0


async def test_swap_bye_player_with_a_contested_player(db):
    t = await _bye_group(db)
    r1 = await _matches(db, t, 1)
    bye = next(m for m in r1 if m.is_bye)
    contested = next(m for m in r1 if not m.is_bye)
    pb = _occupant(bye)
    pc = contested.player_a_id

    await swap_players(db, t, pb, pc)
    await db.commit()

    assert pc in (bye.player_a_id, bye.player_b_id)
    assert pb in (contested.player_a_id, contested.player_b_id)
    # The bye walks its new occupant over; the contested match stays unplayed.
    assert bye.winner_id == pc
    assert await _advanced_into(db, bye) == pc
    assert contested.winner_id is None
    assert contested.status == MatchStatus.pending


async def test_swap_refuses_two_players_who_already_face_each_other(db):
    t = await _bye_group(db)
    contested = next(m for m in await _matches(db, t, 1) if not m.is_bye)
    with pytest.raises(ScoringError, match="already face each other"):
        await swap_players(db, t, contested.player_a_id, contested.player_b_id)


async def test_swap_blocked_when_a_byes_next_round_match_has_started(db):
    t = await _bye_group(db)
    byes = [m for m in await _matches(db, t, 1) if m.is_bye]
    first, second = byes[0], byes[1]
    # Make the Round-2 match the first bye feeds look started.
    nxt = await db.get(Match, first.next_match_id)
    nxt.status = MatchStatus.in_progress
    await db.commit()

    with pytest.raises(ScoringError, match="next-round match"):
        await swap_players(db, t, _occupant(first), _occupant(second))


# --------------------------------------------------------------------------
# Moving players between groups
# --------------------------------------------------------------------------
async def test_move_to_group_relocates_and_keeps_sizes_balanced(drawn):
    db = drawn
    before = {}
    for label in GROUP_LABELS:
        before[label] = len(
            (
                await db.execute(
                    select(Player).where(
                        Player.category == Category.men, Player.group_label == label
                    )
                )
            )
            .scalars()
            .all()
        )

    # Move two players who aren't already in D.
    movers = (
        (
            await db.execute(
                select(Player)
                .where(Player.category == Category.men, Player.group_label != "D")
                .order_by(Player.id)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    phones = [p.phone_normalized for p in movers]

    result = await move_players_to_groups(db, phones, ["D"], Category.men)
    await db.commit()

    assert result["not_found"] == []
    assert result["failed"] == []
    assert len(result["moved"]) == 2
    for p in movers:
        await db.refresh(p)
        assert p.group_label == "D"

    after = {}
    for label in GROUP_LABELS:
        after[label] = len(
            (
                await db.execute(
                    select(Player).where(
                        Player.category == Category.men, Player.group_label == label
                    )
                )
            )
            .scalars()
            .all()
        )
    assert after == before, "swapping partners must preserve every group's size"
    assert "D" in result["redrawn_groups"]


async def test_move_to_group_reports_unknown_phones(drawn):
    result = await move_players_to_groups(drawn, ["9999999999"], ["B"], Category.men)
    assert result["not_found"] == ["9999999999"]
    assert result["moved"] == []


async def test_move_to_group_refuses_to_discard_results(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "B")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    await apply_scores(db, m, [GameInput(1, 21, 10)], "admin")
    await db.commit()

    mover = (
        (
            await db.execute(
                select(Player)
                .where(Player.category == Category.men, Player.group_label == "A")
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    with pytest.raises(ScoringError, match="already has match results"):
        await move_players_to_groups(db, [mover.phone_normalized], ["B"], Category.men)


async def test_move_to_group_rejects_an_unknown_group(drawn):
    with pytest.raises(ScoringError):
        await move_players_to_groups(drawn, [], ["Z"], Category.men)


# --------------------------------------------------------------------------
# Day scheduling
# --------------------------------------------------------------------------
async def test_schedule_day_fills_courts_earliest_round_first(drawn):
    db = drawn
    result = await schedule_day(
        db,
        [{"category": "men", "group": "A"}],
        day_label="Sat",
        start="09:00",
        end="12:00",
        courts=["Court 1", "Court 2"],
        minutes_per_match=10,
    )
    assert result["scheduled"] == result["total_playable"]
    assert result["unscheduled"] == 0

    t = await find_tournament(db, Category.men, "A")
    timed = [m for m in await _matches(db, t) if m.scheduled_time]
    assert timed, "something should have been scheduled"
    assert all(m.scheduled_time.startswith("Sat ") for m in timed)
    assert all("Court" in m.scheduled_time for m in timed)
    # Byes are not played, so they never get a slot.
    assert all(not m.is_bye for m in timed)
    # Round 1 gets the first slot of the day.
    r1 = [m for m in timed if m.round_number == 1]
    assert any("9:00am" in m.scheduled_time for m in r1)


async def test_schedule_day_holds_over_unavailable_players(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    absent = await db.get(Player, m.player_a_id)

    result = await schedule_day(
        db,
        [{"category": "men", "group": "A"}],
        day_label="Sat",
        start="09:00",
        end="18:00",
        courts=["Court 1"],
        minutes_per_match=10,
        unavailable_phones=[absent.phone_normalized],
    )
    assert result["held_over"] >= 1
    await db.refresh(m)
    assert m.scheduled_time is None


async def test_schedule_day_capacity_is_respected(drawn):
    db = drawn
    result = await schedule_day(
        db,
        [{"category": "men", "group": "A"}],
        day_label="Sat",
        start="09:00",
        end="09:20",  # 2 slots on 1 court
        courts=["Court 1"],
        minutes_per_match=10,
    )
    assert result["slots_available"] == 2
    assert result["scheduled"] == 2
    assert result["unscheduled"] == result["total_playable"] - 2


async def test_schedule_day_second_pass_only_fills_the_gaps(drawn):
    db = drawn
    targets = [{"category": "men", "group": "A"}]
    first = await schedule_day(
        db, targets, "Sat", "09:00", "09:20", ["Court 1"], 10
    )
    assert first["unscheduled"] > 0

    t = await find_tournament(db, Category.men, "A")
    already = {
        m.id: m.scheduled_time for m in await _matches(db, t) if m.scheduled_time
    }
    second = await schedule_day(
        db, targets, "Sun", "09:00", "18:00", ["Court 1"], 10, None, True
    )
    assert second["scheduled"] == first["unscheduled"]
    for m in await _matches(db, t):
        if m.id in already:
            assert m.scheduled_time == already[m.id], "day one's times must survive"


async def test_schedule_day_validates_its_inputs(drawn):
    db = drawn
    targets = [{"category": "men", "group": "A"}]
    with pytest.raises(ScoringError):
        await schedule_day(db, [], "Sat", "09:00", "12:00", ["Court 1"], 10)
    with pytest.raises(ScoringError):
        await schedule_day(db, targets, "Sat", "09:00", "12:00", [], 10)
    with pytest.raises(ScoringError):
        await schedule_day(db, targets, "Sat", "09:00", "12:00", ["Court 1"], 0)
    with pytest.raises(ScoringError, match="End time must be after"):
        await schedule_day(db, targets, "Sat", "12:00", "09:00", ["Court 1"], 10)


async def test_clear_schedule_wipes_only_the_named_groups(drawn):
    db = drawn
    await schedule_day(db, [{"category": "men", "group": "A"}], "Sat", "09:00", "18:00", ["C1"], 10)
    await schedule_day(db, [{"category": "men", "group": "B"}], "Sat", "09:00", "18:00", ["C1"], 10)

    result = await clear_schedule(db, [{"category": "men", "group": "A"}])
    assert result["cleared"] > 0

    a = await find_tournament(db, Category.men, "A")
    b = await find_tournament(db, Category.men, "B")
    assert all(m.scheduled_time is None for m in await _matches(db, a))
    assert any(m.scheduled_time for m in await _matches(db, b))


# --------------------------------------------------------------------------
# Paste-to-schedule
# --------------------------------------------------------------------------
async def test_schedule_specific_players_from_pasted_text(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    a = await db.get(Player, m.player_a_id)

    text = f"1. {a.full_name} +91 {a.phone_normalized}\n2. someone else 0000"
    result = await schedule_specific_players(
        db, text, day_label="Sun", start="16:00", courts=["Court 3"], minutes_per_match=8
    )
    assert len(result["scheduled"]) == 1
    assert result["scheduled"][0]["match_id"] == m.id
    await db.refresh(m)
    assert m.scheduled_time == "Sun 4:00pm Court 3"


async def test_schedule_specific_dedupes_two_players_in_the_same_match(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    m = next(x for x in await _matches(db, t, 1) if not x.is_bye and x.player_b_id)
    a = await db.get(Player, m.player_a_id)
    b = await db.get(Player, m.player_b_id)

    text = f"{a.phone_normalized}\n{b.phone_normalized}"
    result = await schedule_specific_players(db, text, "Sun", "16:00", ["Court 3"], 8)
    assert len(result["scheduled"]) == 1, "both players share one match"


async def test_schedule_specific_reports_unknown_numbers(drawn):
    result = await schedule_specific_players(
        drawn, "call me on 9999999999", "Sun", "16:00", ["Court 3"], 8
    )
    assert result["not_found"] == ["9999999999"]
    assert result["scheduled"] == []


async def test_schedule_specific_needs_a_phone_number(drawn):
    with pytest.raises(ScoringError, match="No phone numbers"):
        await schedule_specific_players(drawn, "no digits here", "Sun", "16:00", ["C"], 8)


# --------------------------------------------------------------------------
# Locking
# --------------------------------------------------------------------------
async def test_rebuild_skips_locked_groups(drawn):
    db = drawn
    t = await find_tournament(db, Category.men, "A")
    before = [(m.id, m.player_a_id, m.player_b_id) for m in await _matches(db, t, 1)]
    t.status = TournamentStatus.locked
    await db.commit()

    result = await rebuild_men(db, seed=999)
    await db.commit()
    assert result["groups"]["A"] == {"skipped": "locked"}

    after = [(m.id, m.player_a_id, m.player_b_id) for m in await _matches(db, t, 1)]
    assert after == before, "a locked draw must not be regenerated"


async def test_rebuild_women_skips_when_locked(drawn):
    db = drawn
    t = await find_tournament(db, Category.women, None)
    t.status = TournamentStatus.locked
    await db.commit()
    assert await rebuild_women(db, seed=5) == {"skipped": "locked"}


async def test_generating_a_draw_needs_two_players(db):
    """A group with a single entrant has no bracket to build."""
    t = Tournament(category=Category.women, status=TournamentStatus.draft)
    db.add(t)
    db.add(
        Player(
            full_name="Only One",
            phone_normalized="9000000001",
            dedup_key="ph:9000000001",
            category=Category.women,
        )
    )
    await db.commit()
    with pytest.raises(ValueError):
        await rebuild_women(db, seed=1)
