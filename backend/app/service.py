"""Orchestration: create tournaments, assign groups, generate all draws."""
from __future__ import annotations

import random
import re

from sqlalchemy.orm import Session

from .csv_import import dedup_key_for, normalize_phone
from .draw import generate_draw
from .grouping import GROUP_LABELS, assign_men_groups, experience_rank
from .models import Category, Match, MatchStatus, Player, RoundFormat, Tournament, TournamentStatus
from .scoring import ScoringError, _advance, _is_started, _slot_is_a, _withdraw


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


def remove_player(db: Session, player_id: int) -> dict:
    """Remove a player (withdrawal). If they're in a not-yet-played Round-1 match,
    the opponent gets a walkover and advances. Blocks if the player has already
    played or advanced into a started match (reset those first)."""
    p = db.get(Player, player_id)
    if p is None:
        raise ScoringError("Player not found.")
    name = p.full_name

    r1 = (
        db.query(Match)
        .filter(
            Match.round_number == 1,
            (Match.player_a_id == p.id) | (Match.player_b_id == p.id),
        )
        .one_or_none()
    )
    if r1 is not None:
        nxt = db.get(Match, r1.next_match_id) if r1.next_match_id else None
        # They already won a real match and moved on.
        if r1.status == MatchStatus.completed and not r1.is_bye:
            raise ScoringError("This player has already played a match — reset it first, then remove.")
        # They advanced (via bye) into a match that has started.
        if r1.winner_id is not None and _is_started(nxt):
            raise ScoringError("The next-round match has already started — reset it first, then remove.")

        # Pull any advancement this match produced back out.
        if r1.winner_id is not None and nxt is not None:
            _withdraw(db, r1)

        # Vacate the player's slot.
        if r1.player_a_id == p.id:
            r1.player_a_id = None
        else:
            r1.player_b_id = None
        for g in list(r1.games):
            db.delete(g)

        opponent = r1.player_a_id if r1.player_a_id is not None else r1.player_b_id
        if opponent is not None:
            # Opponent walks over into the next round.
            r1.is_bye = True
            r1.winner_id = opponent
            r1.status = MatchStatus.completed
            _advance(db, r1)
        else:
            r1.is_bye = False
            r1.winner_id = None
            r1.status = MatchStatus.pending
        db.flush()

    db.delete(p)
    db.flush()
    return {"removed": player_id, "name": name}


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



# --------------------------------------------------------------------------
# Moving players between groups (day-scheduling: e.g. "these can only come Sunday")
# --------------------------------------------------------------------------
def _group_has_played_matches(db: Session, tournament: Tournament) -> bool:
    """True if any real (non-bye) match in this group already has a result."""
    return (
        db.query(Match)
        .filter(
            Match.tournament_id == tournament.id,
            Match.is_bye.is_(False),
            (Match.winner_id.isnot(None)) | (Match.status != MatchStatus.pending),
        )
        .first()
        is not None
    )


def move_players_to_groups(
    db: Session,
    phones: list[str],
    target_groups: list[str],
    category: Category = Category.men,
) -> dict:
    """Move the given players into `target_groups`, keeping group sizes balanced.

    Each player who isn't already in a target group is swapped with someone who
    is (and who isn't themselves on the move list), so every group keeps its
    size and its bracket shape. Affected groups are then redrawn.

    Refuses if any affected group has already played matches, so this can never
    silently discard scores.
    """
    target_groups = [g.strip().upper() for g in target_groups if g.strip()]
    if not target_groups:
        raise ScoringError("Pick at least one target group.")
    for g in target_groups:
        if g not in GROUP_LABELS:
            raise ScoringError(f"Unknown group {g!r}.")

    # --- Resolve the phone list to players ---
    wanted: list[Player] = []
    not_found: list[str] = []
    seen_ids: set[int] = set()
    for raw in phones:
        norm = normalize_phone(raw)
        if not norm:
            not_found.append(raw)
            continue
        p = (
            db.query(Player)
            .filter(Player.phone_normalized == norm, Player.category == category)
            .one_or_none()
        )
        if p is None:
            not_found.append(raw)
        elif p.id not in seen_ids:
            seen_ids.add(p.id)
            wanted.append(p)

    protected = {p.id for p in wanted}
    already = [p for p in wanted if p.group_label in target_groups]
    to_move = [p for p in wanted if p.group_label not in target_groups]

    # --- Guard: never wipe entered scores ---
    affected_labels = {p.group_label for p in to_move if p.group_label} | set(target_groups)
    tournaments = {
        g: db.query(Tournament)
        .filter(Tournament.category == category, Tournament.group_label == g)
        .one_or_none()
        for g in affected_labels
    }
    for g, t in tournaments.items():
        if t is None:
            continue
        if t.status == TournamentStatus.locked:
            raise ScoringError(f"Group {g} is locked. Unlock it before moving players.")
        if _group_has_played_matches(db, t):
            raise ScoringError(
                f"Group {g} already has match results. Moving players would discard them."
            )

    # --- Swap each mover with a partner from a target group ---
    moved: list[dict] = []
    failed: list[dict] = []
    # Round-robin across the target groups so they stay evenly filled.
    order = list(target_groups)
    idx = 0
    for p in to_move:
        placed = False
        for _ in range(len(order)):
            target = order[idx % len(order)]
            idx += 1
            partner = (
                db.query(Player)
                .filter(
                    Player.category == category,
                    Player.group_label == target,
                    Player.id.notin_(protected),
                )
                .order_by(Player.id)
                .first()
            )
            if partner is None:
                continue
            origin = p.group_label
            p.group_label = target
            partner.group_label = origin
            protected.add(partner.id)  # don't bounce them back out
            affected_labels.add(origin or "")
            affected_labels.add(target)
            moved.append(
                {
                    "name": p.full_name,
                    "phone": p.phone_normalized,
                    "from": origin,
                    "to": target,
                    "swapped_with": partner.full_name,
                }
            )
            placed = True
            break
        if not placed:
            failed.append({"name": p.full_name, "reason": "no swap partner available"})
    db.flush()

    # --- Redraw every affected group so brackets match the new rosters ---
    redrawn = []
    for g in sorted(x for x in affected_labels if x):
        t = (
            db.query(Tournament)
            .filter(Tournament.category == category, Tournament.group_label == g)
            .one_or_none()
        )
        if t is None or t.status == TournamentStatus.locked:
            continue
        generate_draw(db, t)
        redrawn.append(g)

    db.commit()
    return {
        "moved": moved,
        "already_in_target": [
            {"name": p.full_name, "group": p.group_label} for p in already
        ],
        "not_found": not_found,
        "failed": failed,
        "redrawn_groups": redrawn,
    }


# --------------------------------------------------------------------------
# Match scheduling: lay matches onto courts across a day's playing window
# --------------------------------------------------------------------------
def _parse_hhmm(value: str) -> int:
    """'17:00' -> minutes since midnight."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", value or "")
    if not m:
        raise ScoringError(f"Time must look like 17:00, got {value!r}.")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ScoringError(f"Not a valid time: {value!r}.")
    return h * 60 + mi


def _fmt_hhmm(total: int) -> str:
    h, m = divmod(total % (24 * 60), 60)
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{suffix}"


def schedule_day(
    db: Session,
    targets: list[dict],
    day_label: str,
    start: str,
    end: str,
    courts: list[str],
    minutes_per_match: int,
) -> dict:
    """Assign times+courts to matches, earliest round first.

    Rounds are filled in order across all selected groups, so if the day runs
    out of time it is always the LATEST rounds that go unscheduled — never a
    half-finished early round. Byes are skipped (nothing to play).
    """
    if not targets:
        raise ScoringError("Pick at least one group to schedule.")
    if not courts:
        raise ScoringError("Need at least one court.")
    if minutes_per_match < 1:
        raise ScoringError("Minutes per match must be at least 1.")

    start_min, end_min = _parse_hhmm(start), _parse_hhmm(end)
    if end_min <= start_min:
        raise ScoringError("End time must be after start time.")

    # Collect the tournaments named by `targets`.
    tournaments: list[Tournament] = []
    for tgt in targets:
        cat = Category(tgt["category"])
        grp = tgt.get("group") or None
        t = (
            db.query(Tournament)
            .filter(Tournament.category == cat)
            .filter(
                Tournament.group_label.is_(None)
                if grp is None
                else Tournament.group_label == grp
            )
            .one_or_none()
        )
        if t is None:
            raise ScoringError(f"No draw for {cat.value} {grp or ''}".strip() + ".")
        tournaments.append(t)

    # All playable matches, earliest round first, groups interleaved within a round.
    matches = (
        db.query(Match)
        .filter(
            Match.tournament_id.in_([t.id for t in tournaments]),
            Match.is_bye.is_(False),
        )
        .order_by(Match.round_number, Match.position_in_round, Match.tournament_id)
        .all()
    )

    slots_total = ((end_min - start_min) // minutes_per_match) * len(courts)
    scheduled = 0
    per_round: dict[int, int] = {}
    last_time = None

    for i, m in enumerate(matches):
        if i >= slots_total:
            m.scheduled_time = None  # beyond the day's capacity
            continue
        slot, court_idx = divmod(i, len(courts))
        t_min = start_min + slot * minutes_per_match
        stamp = f"{day_label} {_fmt_hhmm(t_min)} {courts[court_idx]}".strip()
        m.scheduled_time = stamp
        scheduled += 1
        per_round[m.round_number] = per_round.get(m.round_number, 0) + 1
        last_time = _fmt_hhmm(t_min + minutes_per_match)

    db.commit()
    return {
        "scheduled": scheduled,
        "unscheduled": max(0, len(matches) - scheduled),
        "total_playable": len(matches),
        "slots_available": slots_total,
        "per_round": {str(k): v for k, v in sorted(per_round.items())},
        "finishes_by": last_time,
        "courts": courts,
        "minutes_per_match": minutes_per_match,
    }


def clear_schedule(db: Session, targets: list[dict]) -> dict:
    """Wipe scheduled times for the given groups."""
    ids = []
    for tgt in targets:
        cat = Category(tgt["category"])
        grp = tgt.get("group") or None
        t = (
            db.query(Tournament)
            .filter(Tournament.category == cat)
            .filter(
                Tournament.group_label.is_(None)
                if grp is None
                else Tournament.group_label == grp
            )
            .one_or_none()
        )
        if t is not None:
            ids.append(t.id)
    n = 0
    for m in db.query(Match).filter(Match.tournament_id.in_(ids)).all():
        if m.scheduled_time:
            m.scheduled_time = None
            n += 1
    db.commit()
    return {"cleared": n}
