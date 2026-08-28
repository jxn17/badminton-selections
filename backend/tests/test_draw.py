"""Draw-engine tests across many entry counts."""
from __future__ import annotations

import pytest

from app.draw import (
    build_draw_plan,
    bye_slot_positions,
    fisher_yates,
    generate_draw,
    next_power_of_two,
    seed_slot_order,
)
from app.models import Category, Match, Player, Tournament, TournamentStatus

COUNTS = [2, 3, 5, 6, 7, 8, 13, 16, 17, 31, 32]


@pytest.mark.parametrize("n", COUNTS)
def test_power_of_two_and_byes(n):
    p = next_power_of_two(n)
    assert p >= n and p // 2 < n  # smallest power of two >= n
    b = p - n
    # The core invariant that guarantees no bye-vs-bye.
    assert b < p / 2


@pytest.mark.parametrize("n", COUNTS)
def test_plan_structure(n):
    ids = list(range(1, n + 1))
    plan = build_draw_plan(ids, seed=4242)

    assert plan.bracket_size == next_power_of_two(n)
    assert plan.num_byes == plan.bracket_size - n

    round1 = plan.rounds[0]
    assert len(round1) == plan.bracket_size // 2

    # No bye is ever paired against another bye.
    for m in round1:
        assert not (m.player_a is None and m.player_b is None)

    # Every real player appears exactly once in Round 1.
    seen = []
    for m in round1:
        for pid in (m.player_a, m.player_b):
            if pid is not None:
                seen.append(pid)
    assert sorted(seen) == ids

    # Bye matches resolve immediately to the present player.
    byes = [m for m in round1 if m.is_bye]
    assert len(byes) == plan.num_byes
    for m in byes:
        assert m.winner in (m.player_a, m.player_b) and m.winner is not None

    # Every match chains to a valid next match, up to the Final.
    num_rounds = len(plan.rounds)
    for r_idx, rnd in enumerate(plan.rounds):
        for m in rnd:
            if r_idx == num_rounds - 1:
                assert m.next_position is None  # final has no successor
            else:
                nxt = plan.rounds[r_idx + 1]
                assert m.next_position is not None
                assert 0 <= m.next_position < len(nxt)
    # Final round is a single match.
    assert len(plan.rounds[-1]) == 1


def test_reproducible_with_seed():
    ids = list(range(1, 18))
    a = build_draw_plan(ids, seed=99)
    b = build_draw_plan(ids, seed=99)
    a_slots = [(m.player_a, m.player_b) for m in a.rounds[0]]
    b_slots = [(m.player_a, m.player_b) for m in b.rounds[0]]
    assert a_slots == b_slots
    # A different seed should (almost surely) differ.
    c = build_draw_plan(ids, seed=100)
    c_slots = [(m.player_a, m.player_b) for m in c.rounds[0]]
    assert c_slots != a_slots


def test_fisher_yates_is_permutation():
    ids = list(range(50))
    out = fisher_yates(ids, seed=7)
    assert sorted(out) == ids
    assert fisher_yates(ids, seed=7) == out  # deterministic


def test_bye_slots_spread_for_p8():
    # seeds-in-slot order for size 8 is [1,8,4,5,2,7,3,6]; seeds 1,2,3 sit at 0,4,6.
    assert seed_slot_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert bye_slot_positions(8, 3) == [0, 4, 6]


def test_refuses_fewer_than_two():
    with pytest.raises(ValueError):
        build_draw_plan([1], seed=1)


def _make_players(db, n, category=Category.men):
    players = []
    for i in range(n):
        p = Player(
            full_name=f"P{i}",
            phone_raw=str(9000000000 + i),
            phone_normalized=str(9000000000 + i),
            dedup_key=f"ph:{9000000000 + i}",
            category=category,
        )
        db.add(p)
        players.append(p)
    db.flush()
    return players


@pytest.mark.parametrize("n", [5, 7, 16, 17])
def test_generate_draw_persists_and_wires(db, n):
    _make_players(db, n)
    t = Tournament(category=Category.men, status=TournamentStatus.draft)
    db.add(t)
    db.flush()

    generate_draw(db, t, seed=123)
    db.commit()

    assert t.bracket_size == next_power_of_two(n)
    assert t.num_byes == t.bracket_size - n
    assert t.draw_seed == 123

    matches = db.query(Match).filter(Match.tournament_id == t.id).all()
    by_id = {m.id: m for m in matches}

    # next_match_id points to a real match, except for the single final.
    finals = [m for m in matches if m.next_match_id is None]
    assert len(finals) == 1
    for m in matches:
        if m.next_match_id is not None:
            assert m.next_match_id in by_id

    # Bye winners have been advanced into their Round 2 slot.
    for m in matches:
        if m.is_bye:
            assert m.winner_id is not None
            nxt = by_id[m.next_match_id]
            advanced = nxt.player_a_id if m.position_in_round % 2 == 0 else nxt.player_b_id
            assert advanced == m.winner_id


def test_clear_men_draws(db):
    # Setup some players
    _make_players(db, 8)
    # Assign them to group A
    players = db.query(Player).filter(Player.category == Category.men).all()
    for p in players:
        p.group_label = "A"
    
    t = Tournament(category=Category.men, status=TournamentStatus.draft, group_label="A")
    db.add(t)
    db.flush()
    generate_draw(db, t, seed=123)
    db.commit()

    # Verify matches exist
    matches = db.query(Match).filter(Match.tournament_id == t.id).all()
    assert len(matches) > 0
    assert t.bracket_size is not None

    # Call endpoint function directly
    from app.routers.admin import clear_men_draws_endpoint
    res = clear_men_draws_endpoint(db, admin="admin@test.dev")

    # Verify matches are deleted, bracket values reset
    matches_after = db.query(Match).filter(Match.tournament_id == t.id).all()
    assert len(matches_after) == 0
    assert t.bracket_size is None
    assert t.num_byes is None
    assert t.draw_seed is None
    assert t.status == TournamentStatus.draft

    # Verify players' group labels are reset to None
    players_after = db.query(Player).filter(Player.category == Category.men).all()
    for p in players_after:
        assert p.group_label is None
