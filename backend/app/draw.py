"""Single-elimination draw generation.

No seeds — ordering is random — but byes are spread using the *standard* bracket
seed positions so they never clump. The logic is split into pure helpers
(unit-testable, no DB) plus a persistence function that writes the bracket into
the `matches` table wired for advancement.

Bye-placement math
------------------
Let N = number of players, P = smallest power of two >= N, B = P - N byes.

Because P is the *smallest* power of two >= N, the next-smaller power of two
(P/2) is < N, i.e. N > P/2. Therefore:

    B = P - N < P - P/2 = P/2

So B < P/2. Round 1 has P/2 matches, and we place at most one bye per match
(each bye sits on a distinct "top-seed" slot, and those slots live in different
Round-1 matches). Hence **no bye is ever paired against another bye** — proven,
not merely tested (there is also a test asserting it).

Which slots get the byes? In a standard seeded bracket of size P, seed 1 sits at
one end, seed 2 at the other, seeds 3/4 at the quarter boundaries, etc. — a
maximally-spread set of positions. We compute the slots that seeds 1..B would
occupy and drop the byes there. Since there are no real seeds, *which* players
land next to a bye is decided purely by the random shuffle, so it stays fair.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Match, MatchStatus, Player, Tournament
from .scoring import check_and_apply_no_shows


def next_power_of_two(n: int) -> int:
    """Smallest power of two >= n (n >= 1)."""
    p = 1
    while p < n:
        p *= 2
    return p


def seed_slot_order(size: int) -> list[int]:
    """Return a list `slots` of length `size` where slots[i] = the seed (1-based)
    that occupies slot i (0-based) in a standard single-elimination bracket.

    Built by the classic recursive doubling: [1] -> [1, 2] -> [1, 4, 2, 3] -> ...
    where each seed s in a bracket of size n expands to (s, 2n+1-s).
    """
    seeds = [1]
    while len(seeds) < size:
        n = len(seeds) * 2
        expanded: list[int] = []
        for s in seeds:
            expanded.append(s)
            expanded.append(n + 1 - s)
        seeds = expanded
    return seeds


def bye_slot_positions(size: int, num_byes: int) -> list[int]:
    """The `num_byes` slot positions that seeds 1..num_byes occupy (sorted)."""
    slots = seed_slot_order(size)
    slot_of_seed = {seed: idx for idx, seed in enumerate(slots)}
    return sorted(slot_of_seed[s] for s in range(1, num_byes + 1))


def fisher_yates(items: list, seed: int) -> list:
    """In-place-style Fisher–Yates shuffle driven by an explicit RNG seed.

    Returns a new list; same seed + same input => same output (auditable).
    """
    rng = random.Random(seed)
    result = list(items)
    for i in range(len(result) - 1, 0, -1):
        j = rng.randint(0, i)
        result[i], result[j] = result[j], result[i]
    return result


@dataclass
class MatchPlan:
    round_number: int
    position: int  # 0-based within the round
    player_a: int | None = None  # player id or None
    player_b: int | None = None
    is_bye: bool = False
    winner: int | None = None  # set immediately for bye matches
    next_position: int | None = None  # position in the next round this feeds


@dataclass
class DrawPlan:
    bracket_size: int
    num_byes: int
    seed: int
    rounds: list[list[MatchPlan]] = field(default_factory=list)

    @property
    def all_matches(self) -> list[MatchPlan]:
        return [m for rnd in self.rounds for m in rnd]


def build_draw_plan(player_ids: list[int], seed: int) -> DrawPlan:
    """Pure bracket construction. `player_ids` are the real (deduped) entrants."""
    n = len(player_ids)
    if n < 2:
        raise ValueError("Need at least 2 players to generate a draw.")

    size = next_power_of_two(n)
    num_byes = size - n
    bye_slots = set(bye_slot_positions(size, num_byes))

    shuffled = fisher_yates(player_ids, seed)

    # Lay players into the non-bye slots in shuffled order.
    slots: list[int | None] = [None] * size
    it = iter(shuffled)
    for slot in range(size):
        if slot in bye_slots:
            slots[slot] = None  # a bye
        else:
            slots[slot] = next(it)

    plan = DrawPlan(bracket_size=size, num_byes=num_byes, seed=seed)

    # --- Round 1: pair adjacent slots (0v1, 2v3, ...). ---
    round1: list[MatchPlan] = []
    for pos in range(size // 2):
        a = slots[2 * pos]
        b = slots[2 * pos + 1]
        is_bye = (a is None) or (b is None)
        winner = None
        if is_bye:
            # Exactly one side is a real player (B < P/2 guarantees never both).
            winner = a if a is not None else b
        round1.append(
            MatchPlan(
                round_number=1,
                position=pos,
                player_a=a,
                player_b=b,
                is_bye=is_bye,
                winner=winner,
                # If size == 2, Round 1 *is* the final: no successor.
                next_position=(pos // 2 if size >= 4 else None),
            )
        )
    plan.rounds.append(round1)

    # --- Subsequent rounds: empty placeholders wired by position. ---
    round_number = 2
    matches_in_round = size // 4
    while matches_in_round >= 1:
        rnd = [
            MatchPlan(
                round_number=round_number,
                position=pos,
                next_position=(pos // 2 if matches_in_round > 1 else None),
            )
            for pos in range(matches_in_round)
        ]
        plan.rounds.append(rnd)
        matches_in_round //= 2
        round_number += 1

    # --- Pre-advance bye winners into Round 2 (their opponent slot). ---
    if len(plan.rounds) > 1:
        for m in plan.rounds[0]:
            if m.is_bye and m.winner is not None:
                _place_into(plan.rounds[1][m.next_position], m.position, m.winner)

    return plan


def _place_into(target: MatchPlan, from_position: int, player_id: int) -> None:
    """Put an advancing player into the correct A/B slot of the downstream match.

    Even source position -> slot A, odd -> slot B (positions 0,1 feed match 0, etc.).
    """
    if from_position % 2 == 0:
        target.player_a = player_id
    else:
        target.player_b = player_id


# --------------------------------------------------------------------------
# DB persistence
# --------------------------------------------------------------------------
def generate_draw(db: Session, tournament: Tournament, seed: int | None = None) -> Tournament:
    """(Re)generate the bracket for a *draft* tournament and persist it.

    Wipes any existing matches, builds a fresh plan, writes Match rows, and wires
    next_match_id. Stores bracket_size, num_byes and draw_seed for auditability.
    """
    # Players for THIS tournament: category + its group (women have group_label=None).
    q = db.query(Player).filter(Player.category == tournament.category)
    if tournament.group_label is None:
        q = q.filter(Player.group_label.is_(None))
    else:
        q = q.filter(Player.group_label == tournament.group_label)
    players = q.order_by(Player.id).all()
    player_ids = [p.id for p in players]
    if len(player_ids) < 2:
        label = tournament.group_label or "(all)"
        raise ValueError(
            f"Cannot draw {tournament.category.value} group {label}: "
            f"need >= 2 players, have {len(player_ids)}."
        )

    if seed is None:
        # Deterministic-but-varied default seed; explicitly stored either way.
        seed = random.SystemRandom().randint(1, 2**31 - 1)

    plan = build_draw_plan(player_ids, seed)

    # Clear previous matches (draft only — caller enforces status).
    for m in list(tournament.matches):
        db.delete(m)
    db.flush()

    # Create rows round by round, keeping a position->Match index per round.
    created: list[dict[int, Match]] = []
    for rnd in plan.rounds:
        by_pos: dict[int, Match] = {}
        for mp in rnd:
            match = Match(
                tournament_id=tournament.id,
                round_number=mp.round_number,
                position_in_round=mp.position,
                player_a_id=mp.player_a,
                player_b_id=mp.player_b,
                is_bye=mp.is_bye,
                winner_id=mp.winner,
                status=MatchStatus.completed if mp.winner is not None else MatchStatus.pending,
            )
            db.add(match)
            by_pos[mp.position] = match
        db.flush()  # assign ids for this round before wiring
        created.append(by_pos)

    # Wire next_match_id using each plan match's next_position.
    for r_idx, rnd in enumerate(plan.rounds):
        for mp in rnd:
            if mp.next_position is not None:
                child = created[r_idx + 1][mp.next_position]
                created[r_idx][mp.position].next_match_id = child.id

    tournament.bracket_size = plan.bracket_size
    tournament.num_byes = plan.num_byes
    tournament.draw_seed = seed
    db.flush()

    # Apply no-shows to the newly generated matches round-by-round
    for r_idx in range(len(plan.rounds)):
        for mp in plan.rounds[r_idx]:
            match = created[r_idx][mp.position]
            check_and_apply_no_shows(db, match)

    return tournament
