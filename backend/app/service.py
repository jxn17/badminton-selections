"""Orchestration: create tournaments, assign groups, generate all draws."""
from __future__ import annotations

import random
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .csv_import import dedup_key_for, extract_candidate_phones, normalize_phone
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


async def get_or_create_tournament(
    db: AsyncSession, category: Category, group_label: str | None
) -> Tournament:
    t = await find_tournament(db, category, group_label)
    if t is None:
        t = Tournament(category=category, group_label=group_label, status=TournamentStatus.draft)
        db.add(t)
        await db.flush()
        db.add(default_format(t.id))
        await db.flush()
    return t


async def find_tournament(
    db: AsyncSession, category: Category, group_label: str | None
) -> Tournament | None:
    """The one tournament for a (category, group). Women's group_label is NULL."""
    stmt = select(Tournament).where(Tournament.category == category).where(
        Tournament.group_label.is_(None)
        if group_label is None
        else Tournament.group_label == group_label
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def rebuild_men(db: AsyncSession, seed: int | None = None) -> dict:
    """Assign the 4 balanced groups and generate each group's draw (draft only)."""
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    counts = await assign_men_groups(db, seed)

    results = {}
    for i, label in enumerate(GROUP_LABELS):
        t = await get_or_create_tournament(db, Category.men, label)
        if t.status == TournamentStatus.locked:
            results[label] = {"skipped": "locked"}
            continue
        await generate_draw(db, t, seed=seed + 100 + i)
        results[label] = {
            "count": counts[label],
            "bracket_size": t.bracket_size,
            "num_byes": t.num_byes,
        }
    await db.commit()
    return {"seed": seed, "groups": results}


async def rebuild_women(db: AsyncSession, seed: int | None = None) -> dict:
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    t = await get_or_create_tournament(db, Category.women, None)
    if t.status == TournamentStatus.locked:
        await db.commit()
        return {"skipped": "locked"}
    await generate_draw(db, t, seed=seed)
    await db.commit()
    return {"seed": seed, "bracket_size": t.bracket_size, "num_byes": t.num_byes}


# --------------------------------------------------------------------------
# Roster edits: swap players, add walk-ins
# --------------------------------------------------------------------------
async def _round1_slot(
    db: AsyncSession, tournament_id: int, player_id: int
) -> tuple[Match, str] | None:
    """Find the Round-1 match + slot ('a'/'b') where a player currently sits."""
    m = (
        await db.execute(
            select(Match).where(
                Match.tournament_id == tournament_id,
                Match.round_number == 1,
                (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
            )
        )
    ).scalar_one_or_none()
    if m is None:
        return None
    return (m, "a" if m.player_a_id == player_id else "b")


async def swap_players(
    db: AsyncSession, tournament: Tournament, player_x: int, player_y: int
) -> None:
    """Exchange two players' Round-1 positions (rebalancing who plays whom).

    Works whether either player is currently contesting a match OR sitting on a
    bye — which is the common case, since a draw with byes has most of its field
    on one. Swapping onto or off a bye re-settles that match's automatic
    walkover winner and its Round-2 advancement, so the bracket stays valid.

    Refuses only when a swap would discard a real result: a contested match that
    has actually been played, or a bye whose winner has already advanced into a
    Round-2 match that has itself started (reset that one first).
    """
    if player_x == player_y:
        raise ScoringError("Pick two different players to swap.")
    sx = await _round1_slot(db, tournament.id, player_x)
    sy = await _round1_slot(db, tournament.id, player_y)
    if sx is None or sy is None:
        raise ScoringError("Both players must be in this group's first round.")
    (mx, slot_x), (my, slot_y) = sx, sy

    if mx.id == my.id:
        raise ScoringError("Those two players already face each other.")

    for m in (mx, my):
        if not m.is_bye:
            # A contested match that has been played can't be reshuffled without
            # throwing away its scores.
            if m.games or m.winner_id is not None or m.status != MatchStatus.pending:
                raise ScoringError("Can't swap a player whose match has already been played.")
        else:
            # A bye's winner already sits in Round 2; only safe to move them while
            # that downstream match hasn't started.
            nxt = await db.get(Match, m.next_match_id) if m.next_match_id else None
            if _is_started(nxt):
                raise ScoringError(
                    "Can't swap: the next-round match has already started. Reset it first."
                )

    # Pull each bye's auto-advanced winner back out of Round 2 before moving anyone.
    for m in (mx, my):
        if m.is_bye and m.winner_id is not None:
            await _withdraw(db, m)

    # Physically exchange the two players between their slots. is_bye is
    # unchanged — each match keeps the same number of filled slots, only the
    # identity of the real player in it changes.
    setattr(mx, f"player_{slot_x}_id", player_y)
    setattr(my, f"player_{slot_y}_id", player_x)
    await db.flush()

    # Re-settle each bye: its lone new occupant is the walkover winner, advanced
    # into Round 2 in place of whoever we just withdrew.
    for m in (mx, my):
        if m.is_bye:
            m.winner_id = m.player_a_id if m.player_a_id is not None else m.player_b_id
            m.status = MatchStatus.completed
            await _advance(db, m)
    await db.flush()


async def add_walkin(
    db: AsyncSession,
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
        rows = await db.execute(
            select(Player.group_label).where(Player.category == Category.men)
        )
        for (g,) in rows:
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
    await db.flush()

    placed_into = await _place_into_open_bye(db, category, group_label, player.id)
    return {
        "player_id": player.id,
        "group_label": group_label,
        "placed": placed_into is not None,
        "match_id": placed_into,
    }


async def remove_player(db: AsyncSession, player_id: int) -> dict:
    """Remove a player (withdrawal). If they're in a not-yet-played Round-1 match,
    the opponent gets a walkover and advances. Blocks if the player has already
    played or advanced into a started match (reset those first)."""
    p = await db.get(Player, player_id)
    if p is None:
        raise ScoringError("Player not found.")
    name = p.full_name

    r1 = (
        await db.execute(
            select(Match).where(
                Match.round_number == 1,
                (Match.player_a_id == p.id) | (Match.player_b_id == p.id),
            )
        )
    ).scalar_one_or_none()
    if r1 is not None:
        nxt = await db.get(Match, r1.next_match_id) if r1.next_match_id else None
        # They already won a real match and moved on.
        if r1.status == MatchStatus.completed and not r1.is_bye:
            raise ScoringError("This player has already played a match — reset it first, then remove.")
        # They advanced (via bye) into a match that has started.
        if r1.winner_id is not None and _is_started(nxt):
            raise ScoringError("The next-round match has already started — reset it first, then remove.")

        # Pull any advancement this match produced back out.
        if r1.winner_id is not None and nxt is not None:
            await _withdraw(db, r1)

        # Vacate the player's slot.
        if r1.player_a_id == p.id:
            r1.player_a_id = None
        else:
            r1.player_b_id = None
        r1.games.clear()

        opponent = r1.player_a_id if r1.player_a_id is not None else r1.player_b_id
        if opponent is not None:
            # Opponent walks over into the next round.
            r1.is_bye = True
            r1.winner_id = opponent
            r1.status = MatchStatus.completed
            await _advance(db, r1)
        else:
            r1.is_bye = False
            r1.winner_id = None
            r1.status = MatchStatus.pending
        await db.flush()

    await db.delete(p)
    await db.flush()
    return {"removed": player_id, "name": name}


async def _place_into_open_bye(
    db: AsyncSession, category: Category, group_label: str | None, player_id: int
) -> int | None:
    """Convert an available Round-1 bye (whose next match hasn't started) into a
    real match by dropping the walk-in onto the empty side. Returns match id."""
    t = await find_tournament(db, category, group_label)
    if t is None:
        return None
    byes = (
        (
            await db.execute(
                select(Match)
                .where(
                    Match.tournament_id == t.id,
                    Match.round_number == 1,
                    Match.is_bye.is_(True),
                )
                .order_by(Match.position_in_round)
            )
        )
        .scalars()
        .all()
    )
    for m in byes:
        nxt = await db.get(Match, m.next_match_id) if m.next_match_id else None
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
        await db.flush()
        return m.id
    return None



# --------------------------------------------------------------------------
# Moving players between groups (day-scheduling: e.g. "these can only come Sunday")
# --------------------------------------------------------------------------
async def _group_has_played_matches(db: AsyncSession, tournament: Tournament) -> bool:
    """True if any real (non-bye) match in this group already has a result."""
    row = (
        await db.execute(
            select(Match.id)
            .where(
                Match.tournament_id == tournament.id,
                Match.is_bye.is_(False),
                (Match.winner_id.isnot(None)) | (Match.status != MatchStatus.pending),
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def move_players_to_groups(
    db: AsyncSession,
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
            await db.execute(
                select(Player).where(
                    Player.phone_normalized == norm, Player.category == category
                )
            )
        ).scalars().first()
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
    tournaments = {g: await find_tournament(db, category, g) for g in affected_labels}
    for g, t in tournaments.items():
        if t is None:
            continue
        if t.status == TournamentStatus.locked:
            raise ScoringError(f"Group {g} is locked. Unlock it before moving players.")
        if await _group_has_played_matches(db, t):
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
                await db.execute(
                    select(Player)
                    .where(
                        Player.category == category,
                        Player.group_label == target,
                        Player.id.notin_(protected),
                    )
                    .order_by(Player.id)
                    .limit(1)
                )
            ).scalars().first()
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
    await db.flush()

    # --- Redraw every affected group so brackets match the new rosters ---
    redrawn = []
    for g in sorted(x for x in affected_labels if x):
        t = await find_tournament(db, category, g)
        if t is None or t.status == TournamentStatus.locked:
            continue
        await generate_draw(db, t)
        redrawn.append(g)

    await db.commit()
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


async def schedule_day(
    db: AsyncSession,
    targets: list[dict],
    day_label: str,
    start: str,
    end: str,
    courts: list[str],
    minutes_per_match: int,
    unavailable_phones: list[str] | None = None,
    only_unscheduled: bool = False,
) -> dict:
    """Assign times+courts to matches, earliest round first.

    Rounds are filled in order across all selected groups, so if the day runs
    out of time it is always the LATEST rounds that go unscheduled — never a
    half-finished early round. Byes are skipped (nothing to play).

    `unavailable_phones` are players who cannot play on this day: any match
    involving them is left for another day (useful when part of a draw is split
    across two days). `only_unscheduled` leaves already-timed matches untouched,
    so a second day can pick up exactly what the first could not fit.
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
        t = await find_tournament(db, cat, grp)
        if t is None:
            raise ScoringError(f"No draw for {cat.value} {grp or ''}".strip() + ".")
        tournaments.append(t)

    # Players who can't make this day -> their matches are held over.
    blocked_ids: set[int] = set()
    unknown_phones: list[str] = []
    for raw in unavailable_phones or []:
        norm = normalize_phone(raw)
        p = (
            (
                await db.execute(
                    select(Player).where(Player.phone_normalized == norm).limit(1)
                )
            ).scalars().first()
            if norm
            else None
        )
        if p is None:
            unknown_phones.append(raw)
        else:
            blocked_ids.add(p.id)

    # All playable matches, earliest round first, groups interleaved within a round.
    matches = (
        (
            await db.execute(
                select(Match)
                .where(
                    Match.tournament_id.in_([t.id for t in tournaments]),
                    Match.is_bye.is_(False),
                )
                .order_by(Match.round_number, Match.position_in_round, Match.tournament_id)
            )
        )
        .scalars()
        .all()
    )

    held_over = 0
    playable = []
    for m in matches:
        if only_unscheduled and m.scheduled_time:
            continue  # already has a time from an earlier day
        if blocked_ids and (
            m.player_a_id in blocked_ids or m.player_b_id in blocked_ids
        ):
            held_over += 1
            continue  # someone in this match can't play today
        playable.append(m)

    slots_total = ((end_min - start_min) // minutes_per_match) * len(courts)
    scheduled = 0
    per_round: dict[int, int] = {}
    last_time = None

    for i, m in enumerate(playable):
        if i >= slots_total:
            if not only_unscheduled:
                m.scheduled_time = None  # beyond the day's capacity
            continue
        slot, court_idx = divmod(i, len(courts))
        t_min = start_min + slot * minutes_per_match
        stamp = f"{day_label} {_fmt_hhmm(t_min)} {courts[court_idx]}".strip()
        m.scheduled_time = stamp
        scheduled += 1
        per_round[m.round_number] = per_round.get(m.round_number, 0) + 1
        last_time = _fmt_hhmm(t_min + minutes_per_match)

    await db.commit()
    return {
        "scheduled": scheduled,
        "unscheduled": max(0, len(playable) - scheduled),
        "held_over": held_over,
        "unknown_phones": unknown_phones,
        "total_playable": len(playable),
        "slots_available": slots_total,
        "per_round": {str(k): v for k, v in sorted(per_round.items())},
        "finishes_by": last_time,
        "courts": courts,
        "minutes_per_match": minutes_per_match,
    }


async def clear_schedule(db: AsyncSession, targets: list[dict]) -> dict:
    """Wipe scheduled times for the given groups."""
    ids = []
    for tgt in targets:
        t = await find_tournament(db, Category(tgt["category"]), tgt.get("group") or None)
        if t is not None:
            ids.append(t.id)
    n = 0
    rows = (
        (await db.execute(select(Match).where(Match.tournament_id.in_(ids))))
        .scalars()
        .all()
    )
    for m in rows:
        if m.scheduled_time:
            m.scheduled_time = None
            n += 1
    await db.commit()
    return {"cleared": n}


# --------------------------------------------------------------------------
# Schedule specific players by pasting free text (auto-detects phone numbers)
# --------------------------------------------------------------------------
async def _current_active_match(db: AsyncSession, player: Player) -> Match | None:
    """The match this player is waiting to play right now: their tournament's
    latest non-bye, not-yet-completed match with both slots filled in. Returns
    None if they've been eliminated, already finished their run, or their
    opponent isn't decided yet."""
    t = await find_tournament(db, player.category, player.group_label)
    if t is None:
        return None
    candidates = (
        (
            await db.execute(
                select(Match)
                .where(
                    Match.tournament_id == t.id,
                    Match.is_bye.is_(False),
                    Match.status != MatchStatus.completed,
                    (Match.player_a_id == player.id) | (Match.player_b_id == player.id),
                )
                .order_by(Match.round_number.desc())
            )
        )
        .scalars()
        .all()
    )
    for m in candidates:
        if m.player_a_id is not None and m.player_b_id is not None:
            return m
    return None


async def schedule_specific_players(
    db: AsyncSession,
    text: str,
    day_label: str,
    start: str,
    courts: list[str],
    minutes_per_match: int,
) -> dict:
    """Auto-detect phone numbers in pasted text and lay just THOSE players'
    current matches onto the given day/courts, back to back. Unlike
    schedule_day this targets a curated list of people rather than a whole
    round, e.g. "these specific players confirmed they can play at 4pm."
    """
    if not courts:
        raise ScoringError("Need at least one court.")
    if minutes_per_match < 1:
        raise ScoringError("Minutes per match must be at least 1.")
    start_min = _parse_hhmm(start)

    candidates = extract_candidate_phones(text)
    if not candidates:
        raise ScoringError("No phone numbers found in that text.")

    # Resolve each candidate to a known player (this is what actually filters
    # out false-positive matches like a registration number caught by the regex).
    normalized_to_raw: dict[str, str] = {}
    for raw in candidates:
        norm = normalize_phone(raw)
        if norm and norm not in normalized_to_raw:
            normalized_to_raw[norm] = raw

    players_by_norm = {
        p.phone_normalized: p
        for p in (
            await db.execute(
                select(Player).where(
                    Player.phone_normalized.in_(normalized_to_raw.keys())
                )
            )
        ).scalars()
    }

    resolved: list[Player] = []
    not_found: list[str] = []
    for norm, raw in normalized_to_raw.items():
        p = players_by_norm.get(norm)
        if p is None:
            not_found.append(raw)
        else:
            resolved.append(p)

    # One match per player; a match can cover two of the pasted players at
    # once (they're playing each other) — dedupe by match id, first-seen order.
    seen_match_ids: set[int] = set()
    matches: list[Match] = []
    no_active_match: list[str] = []
    for p in resolved:
        m = await _current_active_match(db, p)
        if m is None:
            no_active_match.append(p.full_name)
            continue
        if m.id not in seen_match_ids:
            seen_match_ids.add(m.id)
            matches.append(m)

    scheduled = []
    for i, m in enumerate(matches):
        slot, court_idx = divmod(i, len(courts))
        t_min = start_min + slot * minutes_per_match
        m.scheduled_time = f"{day_label} {_fmt_hhmm(t_min)} {courts[court_idx]}".strip()
        scheduled.append({"match_id": m.id, "scheduled_time": m.scheduled_time})

    await db.commit()
    return {
        "scheduled": scheduled,
        "not_found": not_found,
        "no_active_match": no_active_match,
        "finishes_by": _fmt_hhmm(start_min + len(matches) * minutes_per_match) if matches else None,
    }
