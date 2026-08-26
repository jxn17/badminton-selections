"""Orchestration: create tournaments, assign groups, generate all draws."""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from .csv_import import dedup_key_for, normalize_phone
from .draw import generate_draw
from .grouping import GROUP_LABELS, assign_men_groups, experience_rank
from .models import Category, Match, MatchStatus, Player, RoundFormat, Tournament, TournamentStatus
from .scoring import ScoringError, _is_started, _slot_is_a


def default_format(tournament_id: int) -> RoundFormat:
    # Standard badminton: single game to 21, win by two, hard cap at 30.
    return RoundFormat(
        tournament_id=tournament_id,
        round_number=None,
        points_to_win=21,
        win_by_two=True,
        hard_cap=30,
        games_to_win_match=1,
    )


def get_or_create_tournament(
    db: Session, category: Category, group_label: str | None
) -> Tournament:
    t = (
        db.query(Tournament)
        .filter(Tournament.category == category)
        .filter(
            Tournament.group_label.is_(None)
            if group_label is None
            else Tournament.group_label == group_label
        )
        .one_or_none()
    )
    if t is None:
        t = Tournament(category=category, group_label=group_label, status=TournamentStatus.draft)
        db.add(t)
        db.flush()
        db.add(default_format(t.id))
        db.flush()
    return t


def rebuild_men(db: Session, seed: int | None = None) -> dict:
    """Assign the 4 balanced groups and generate each group's draw (draft only)."""
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    counts = assign_men_groups(db, seed)

    results = {}
    for i, label in enumerate(GROUP_LABELS):
        t = get_or_create_tournament(db, Category.men, label)
        if t.status == TournamentStatus.locked:
            results[label] = {"skipped": "locked"}
            continue
        generate_draw(db, t, seed=seed + 100 + i)
        results[label] = {
            "count": counts[label],
            "bracket_size": t.bracket_size,
            "num_byes": t.num_byes,
        }
    db.commit()
    return {"seed": seed, "groups": results}


def rebuild_women(db: Session, seed: int | None = None) -> dict:
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    t = get_or_create_tournament(db, Category.women, None)
    if t.status == TournamentStatus.locked:
        db.commit()
        return {"skipped": "locked"}
    generate_draw(db, t, seed=seed)
    db.commit()
    return {"seed": seed, "bracket_size": t.bracket_size, "num_byes": t.num_byes}


# --------------------------------------------------------------------------
# Roster edits: swap players, add walk-ins
# --------------------------------------------------------------------------
def _round1_slot(db: Session, tournament_id: int, player_id: int) -> tuple[Match, str] | None:
    """Find the Round-1 match + slot ('a'/'b') where a player currently sits."""
    m = (
        db.query(Match)
        .filter(
            Match.tournament_id == tournament_id,
            Match.round_number == 1,
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
        )
        .one_or_none()
    )
    if m is None:
        return None
    return (m, "a" if m.player_a_id == player_id else "b")


def swap_players(db: Session, tournament: Tournament, player_x: int, player_y: int) -> None:
    """Swap two players' Round-1 positions (e.g. rebalancing who plays whom).

    Both must be real players in non-bye, not-yet-decided Round-1 matches. This
    keeps the bracket valid without touching byes or advancement.
    """
    if player_x == player_y:
        raise ScoringError("Pick two different players to swap.")
    sx = _round1_slot(db, tournament.id, player_x)
    sy = _round1_slot(db, tournament.id, player_y)
    if sx is None or sy is None:
        raise ScoringError("Both players must be in this group's first round.")
    (mx, slot_x), (my, slot_y) = sx, sy
    for m in (mx, my):
        if m.is_bye:
            raise ScoringError("Can't swap a player who is on a bye. Use replace instead.")
        if m.status == MatchStatus.completed or m.winner_id is not None or m.games:
            raise ScoringError("Can't swap into a match that has already been played.")

    if slot_x == "a":
        mx.player_a_id = player_y
    else:
        mx.player_b_id = player_y
    if slot_y == "a":
        my.player_a_id = player_x
    else:
        my.player_b_id = player_x
    db.flush()


def add_walkin(
    db: Session,
    category: Category,
    name: str,
    phone: str,
    experience: str,
    group_label: str | None,
) -> dict:
    """Add a spot entry and slot them into an open bye in their group if possible."""
    name = " ".join(name.split())
    if not name:
        raise ScoringError("Name is required.")
    phone_norm = normalize_phone(phone)
    key = dedup_key_for(phone_norm, "", name) + ":walkin"

    # For men, auto-pick the smallest group unless one was chosen.
    if category == Category.men and not group_label:
        counts = {g: 0 for g in GROUP_LABELS}
        for (g,) in db.query(Player.group_label).filter(Player.category == Category.men).all():
            if g in counts:
                counts[g] += 1
        group_label = min(counts, key=counts.get)
    if category == Category.women:
        group_label = None

    player = Player(
        full_name=name,
        phone_raw=phone or None,
        phone_normalized=phone_norm,
        dedup_key=key,
        experience_level=experience or None,
        category=category,
        group_label=group_label,
        is_walkin=True,
    )
    db.add(player)
    db.flush()

    placed_into = _place_into_open_bye(db, category, group_label, player.id)
    return {
        "player_id": player.id,
        "group_label": group_label,
        "placed": placed_into is not None,
        "match_id": placed_into,
    }


def _place_into_open_bye(
    db: Session, category: Category, group_label: str | None, player_id: int
) -> int | None:
    """Convert an available Round-1 bye (whose next match hasn't started) into a
    real match by dropping the walk-in onto the empty side. Returns match id."""
    t = (
        db.query(Tournament)
        .filter(Tournament.category == category)
        .filter(
            Tournament.group_label.is_(None)
            if group_label is None
            else Tournament.group_label == group_label
        )
        .one_or_none()
    )
    if t is None:
        return None
    byes = (
        db.query(Match)
        .filter(Match.tournament_id == t.id, Match.round_number == 1, Match.is_bye.is_(True))
        .order_by(Match.position_in_round)
        .all()
    )
    for m in byes:
        nxt = db.get(Match, m.next_match_id) if m.next_match_id else None
        if _is_started(nxt):
            continue  # the bye winner already progressed into a live match
        # Withdraw the auto-advanced bye winner from the next match, then contest it.
        if nxt is not None:
            if _slot_is_a(m):
                nxt.player_a_id = None
            else:
                nxt.player_b_id = None
        if m.player_a_id is None:
            m.player_a_id = player_id
        else:
            m.player_b_id = player_id
        m.is_bye = False
        m.winner_id = None
        m.status = MatchStatus.pending
        db.flush()
        return m.id
    return None

