"""Admin (write) endpoints. Every route requires the shared access-code session."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cache
from ..audit import match_snapshot, record
from ..auth import require_admin
from ..csv_import import dedup_key_for, import_csv, normalize_phone
from ..database import get_db
from ..models import Category, Match, MatchStatus, Player, RoundFormat, Tournament, TournamentStatus
from ..scoring import (
    GameInput,
    ScoringError,
    apply_scores,
    clear_no_show,
    clear_retirement,
    set_no_show,
    set_retirement,
)
from ..service import (
    add_walkin,
    clear_schedule,
    move_players_to_groups,
    rebuild_men,
    rebuild_women,
    remove_player,
    schedule_day,
    schedule_specific_players,
    swap_players,
)
from ..schemas import (
    ClearScheduleIn,
    FlagIn,
    MatchSlotIn,
    MoveToGroupIn,
    NoShowIn,
    PlayerUpdateIn,
    ReportIn,
    ScheduleDayIn,
    ScheduleSpecificIn,
    GenerateDrawIn,
    RetireIn,
    RoundFormatIn,
    RoundFormatOut,
    ScheduleIn,
    ScoreUpdateIn,
    SwapIn,
    WalkinIn,
)


async def bust_public_cache(request: Request):
    """Router-wide teardown: any write here invalidates the public read cache.

    Registered as a yield-dependency so it runs *after* the handler has
    committed, and so it covers every mutating route automatically — including
    ones added later, which a per-handler call would eventually miss.
    """
    yield
    if request.method != "GET":
        cache.invalidate()


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin), Depends(bust_public_cache)],
)


async def _match(db: AsyncSession, match_id: int) -> Match:
    m = await db.get(Match, match_id)
    if m is None:
        raise HTTPException(404, "Match not found.")
    return m


async def _tournament(db: AsyncSession, tournament_id: int) -> Tournament:
    t = await db.get(Tournament, tournament_id)
    if t is None:
        raise HTTPException(404, "Tournament not found.")
    return t


def _scoring_error(exc: ScoringError):
    raise HTTPException(422, detail={"message": exc.message, "game_number": exc.game_number})


# --------------------------------------------------------------------------
# Import + draw building
# --------------------------------------------------------------------------
@router.post("/import")
async def import_entries(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    report = await import_csv(db, content)
    record(db, admin, "import_csv", "players", None, after=report.as_dict())
    await db.commit()
    return report.as_dict()


@router.post("/men/rebuild")
async def build_men(
    body: GenerateDrawIn, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    try:
        result = await rebuild_men(db, seed=body.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record(db, admin, "rebuild_men", "tournament", None, after=result)
    await db.commit()
    return result


@router.post("/women/rebuild")
async def build_women(
    body: GenerateDrawIn, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    try:
        result = await rebuild_women(db, seed=body.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record(db, admin, "rebuild_women", "tournament", None, after=result)
    await db.commit()
    return result


@router.post("/tournaments/{tournament_id}/lock")
async def lock(
    tournament_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    t = await _tournament(db, tournament_id)
    if not await t.awaitable_attrs.matches:
        raise HTTPException(400, "Generate the draw before locking.")
    if t.status != TournamentStatus.draft:
        raise HTTPException(409, "Already locked.")
    t.status = TournamentStatus.locked
    t.locked_at = dt.datetime.now(dt.timezone.utc)
    record(db, admin, "lock", "tournament", t.id, after={"status": "locked"})
    await db.commit()
    return {"status": t.status.value}


@router.post("/tournaments/{tournament_id}/unlock")
async def unlock(
    tournament_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    t = await _tournament(db, tournament_id)
    t.status = TournamentStatus.draft
    t.locked_at = None
    record(db, admin, "unlock", "tournament", t.id, after={"status": "draft"})
    await db.commit()
    return {"status": t.status.value}


# --------------------------------------------------------------------------
# Scoring / match edits
# --------------------------------------------------------------------------
@router.put("/matches/{match_id}/score")
async def update_score(
    match_id: int,
    body: ScoreUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    games = [GameInput(g.game_number, g.score_a, g.score_b) for g in body.games]
    try:
        await apply_scores(db, m, games, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "score_edit", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.post("/matches/{match_id}/retire")
async def retire(
    match_id: int,
    body: RetireIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    try:
        await set_retirement(db, m, body.retired_player_id, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "retire", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.delete("/matches/{match_id}/retire")
async def unretire(
    match_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    try:
        await clear_retirement(db, m, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "clear_retire", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.post("/matches/{match_id}/reset")
async def reset_match(
    match_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    if m.next_match_id is not None:
        nxt = await db.get(Match, m.next_match_id)
        if nxt is not None and (
            nxt.status != MatchStatus.pending or nxt.winner_id is not None or nxt.games
        ):
            raise HTTPException(409, "The next-round match has started. Reset that one first.")
        if nxt is not None:
            if m.position_in_round % 2 == 0:
                nxt.player_a_id = None
            else:
                nxt.player_b_id = None
    m.games.clear()
    m.winner_id = None
    m.retired_player_id = None
    m.no_show_player_id = None
    m.status = MatchStatus.pending
    record(db, admin, "reset_match", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.put("/matches/{match_id}/slot")
async def set_match_slot(
    match_id: int,
    body: MatchSlotIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Put a player into one side of a match, or clear it back to TBD.

    This is the manual override for advancement: a later-round slot that says
    TBD can be filled in directly, without entering a score for the match that
    feeds it. Guarded so it can never silently destroy a result — a match that
    has already been played has to be reset first, and byes are left to the draw
    (use a walk-in to occupy one).
    """
    if body.slot not in ("a", "b"):
        raise HTTPException(422, detail={"message": "Slot must be 'a' or 'b'."})
    m = await _match(db, match_id)

    if m.is_bye:
        raise HTTPException(
            409,
            detail={"message": "This is a bye — add a walk-in to give them an opponent."},
        )
    if m.games or m.winner_id is not None or m.status != MatchStatus.pending:
        raise HTTPException(
            409,
            detail={"message": "This match already has a result. Reset it first, then set the players."},
        )

    player = None
    if body.player_id is not None:
        player = await db.get(Player, body.player_id)
        if player is None:
            raise HTTPException(404, detail={"message": "Player not found."})
        # Confine a player to their own draw; crossing brackets would put someone
        # in a group they were never entered into.
        t = m.tournament
        if player.category != t.category or player.group_label != t.group_label:
            raise HTTPException(
                422,
                detail={"message": f"{player.full_name} isn't in this draw."},
            )
        other = m.player_b_id if body.slot == "a" else m.player_a_id
        if other == player.id:
            raise HTTPException(
                422, detail={"message": "That player is already on the other side of this match."}
            )

    before = match_snapshot(m)
    if body.slot == "a":
        m.player_a_id = body.player_id
    else:
        m.player_b_id = body.player_id
    await db.flush()
    record(db, admin, "set_slot", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.put("/matches/{match_id}/schedule")
async def set_schedule(
    match_id: int,
    body: ScheduleIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    m = await _match(db, match_id)
    before = {"scheduled_time": m.scheduled_time}
    m.scheduled_time = (body.scheduled_time or "").strip() or None
    record(db, admin, "schedule", "match", m.id, before, {"scheduled_time": m.scheduled_time})
    await db.commit()
    return {"id": m.id, "scheduled_time": m.scheduled_time}


# --------------------------------------------------------------------------
# Roster: flag/shortlist, swap, walk-ins
# --------------------------------------------------------------------------
@router.post("/matches/{match_id}/no-show")
async def no_show(
    match_id: int,
    body: NoShowIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    try:
        await set_no_show(db, m, body.no_show_player_id, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "no_show", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.delete("/matches/{match_id}/no-show")
async def clear_no_show_ep(
    match_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    m = await _match(db, match_id)
    before = match_snapshot(m)
    try:
        await clear_no_show(db, m, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "clear_no_show", "match", m.id, before, match_snapshot(m))
    await db.commit()
    return match_snapshot(m)


@router.post("/players/{player_id}/report")
async def report_player(
    player_id: int,
    body: ReportIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    p = await db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found.")
    before = {"reported": p.reported}
    p.reported = body.reported
    record(db, admin, "report_player", "player", p.id, before, {"reported": p.reported})
    await db.commit()
    return {"id": p.id, "reported": p.reported}


@router.post("/schedule-specific")
async def schedule_specific_ep(
    body: ScheduleSpecificIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Paste free text (e.g. a WhatsApp export) — phone numbers are auto-detected
    and each matched player's current match is scheduled onto the given window."""
    try:
        result = await schedule_specific_players(
            db, body.text, body.day_label, body.start, body.courts, body.minutes_per_match
        )
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "schedule_specific", "match", None, after=result)
    await db.commit()
    return result


@router.post("/players/{player_id}/flag")
async def flag_player(
    player_id: int,
    body: FlagIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    p = await db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found.")
    before = {"flagged": p.flagged, "flag_note": p.flag_note}
    p.flagged = body.flagged
    p.flag_note = (body.note or "").strip() or None
    record(db, admin, "flag_player", "player", p.id, before, {"flagged": p.flagged, "flag_note": p.flag_note})
    await db.commit()
    return {"id": p.id, "flagged": p.flagged, "flag_note": p.flag_note}


@router.patch("/players/{player_id}")
async def update_player(
    player_id: int,
    body: PlayerUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Correct an entry: a typo'd name, a wrong phone, a missing reg number.

    Entries come straight off a Google Form filled in by ~400 students, so some
    of them are simply wrong. Everything here is safe to change mid-event — none
    of it affects who plays whom. Category and group are not editable (see
    PlayerUpdateIn); experience level is, and it re-tiers the player the next
    time the men's groups are rebuilt.
    """
    p = await db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found.")

    def snapshot() -> dict:
        return {
            "full_name": p.full_name,
            "phone": p.phone_normalized,
            "registration_number": p.registration_number,
            "year_of_study": p.year_of_study,
            "experience_level": p.experience_level,
            "dedup_key": p.dedup_key,
        }

    before = snapshot()

    if body.full_name is not None:
        name = " ".join(body.full_name.split())
        if not name:
            raise HTTPException(422, detail={"message": "Name can't be empty."})
        p.full_name = name
    if body.phone is not None:
        raw = body.phone.strip()
        norm = normalize_phone(raw)
        if raw and norm is None:
            raise HTTPException(
                422, detail={"message": "That doesn't look like a phone number (need 10 digits)."}
            )
        p.phone_raw = raw or None
        p.phone_normalized = norm
    if body.registration_number is not None:
        p.registration_number = body.registration_number.strip() or None
    if body.year_of_study is not None:
        p.year_of_study = body.year_of_study.strip() or None
    if body.experience_level is not None:
        p.experience_level = body.experience_level.strip() or None

    # Identity is derived from phone -> registration -> name, so correcting any
    # of them can change it. Keep it in step, or re-importing the CSV would file
    # this person as a brand new entry instead of recognising them.
    key = dedup_key_for(p.phone_normalized, p.registration_number or "", p.full_name)
    if p.is_walkin:
        key += ":walkin"
    if key != p.dedup_key:
        clash = (
            await db.execute(
                select(Player).where(
                    Player.dedup_key == key,
                    Player.category == p.category,
                    Player.id != p.id,
                )
            )
        ).scalars().first()
        if clash is not None:
            # The unique index would reject this anyway; say who it collided with.
            raise HTTPException(
                409,
                detail={
                    "message": f"Those details already belong to {clash.full_name}. "
                    "If they're the same person, remove one of the two entries."
                },
            )
        p.dedup_key = key

    record(db, admin, "edit_player", "player", p.id, before, snapshot())
    await db.commit()
    return {
        "id": p.id,
        "full_name": p.full_name,
        "phone": p.phone_normalized,
        "registration_number": p.registration_number,
        "year_of_study": p.year_of_study,
        "experience_level": p.experience_level,
    }


@router.delete("/players/{player_id}")
async def delete_player(
    player_id: int, db: AsyncSession = Depends(get_db), admin: str = Depends(require_admin)
):
    try:
        result = await remove_player(db, player_id)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "remove_player", "player", player_id, after=result)
    await db.commit()
    return result


@router.post("/schedule-day")
async def schedule_day_ep(
    body: ScheduleDayIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Auto-assign match times/courts for one day's play."""
    targets = [{"category": t.category.value, "group": t.group} for t in body.targets]
    try:
        result = await schedule_day(
            db, targets, body.day_label, body.start, body.end,
            body.courts, body.minutes_per_match,
            body.unavailable_phones, body.only_unscheduled,
        )
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "schedule_day", "tournament", None, after=result)
    await db.commit()
    return result


@router.post("/clear-schedule")
async def clear_schedule_ep(
    body: ClearScheduleIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    targets = [{"category": t.category.value, "group": t.group} for t in body.targets]
    result = await clear_schedule(db, targets)
    record(db, admin, "clear_schedule", "tournament", None, after=result)
    await db.commit()
    return result


@router.post("/move-to-group")
async def move_to_group(
    body: MoveToGroupIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Bulk-move men into given groups (e.g. everyone who can only play Sunday)."""
    try:
        result = await move_players_to_groups(db, body.phones, body.target_groups, Category.men)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "move_to_group", "player", None, after=result)
    await db.commit()
    return result


@router.post("/tournaments/{tournament_id}/swap")
async def swap(
    tournament_id: int,
    body: SwapIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    t = await _tournament(db, tournament_id)
    try:
        await swap_players(db, t, body.player_x_id, body.player_y_id)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "swap_players", "tournament", t.id,
           after={"x": body.player_x_id, "y": body.player_y_id})
    await db.commit()
    return {"ok": True}


@router.post("/walkin/{category}")
async def walkin_cat(
    category: str,
    body: WalkinIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    try:
        cat = Category(category)
    except ValueError:
        raise HTTPException(404, "Category must be 'men' or 'women'.") from None
    try:
        result = await add_walkin(db, cat, body.name, body.phone, body.experience, body.group_label)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "add_walkin", "player", result["player_id"], after=result)
    await db.commit()
    return result


# --------------------------------------------------------------------------
# Scoring formats (per tournament/group)
# --------------------------------------------------------------------------
@router.get("/tournaments/{tournament_id}/formats", response_model=list[RoundFormatOut])
async def list_formats(tournament_id: int, db: AsyncSession = Depends(get_db)):
    t = await _tournament(db, tournament_id)
    return (
        (
            await db.execute(
                select(RoundFormat)
                .where(RoundFormat.tournament_id == t.id)
                .order_by(RoundFormat.round_number.nullsfirst())
            )
        )
        .scalars()
        .all()
    )


@router.put("/tournaments/{tournament_id}/formats", response_model=RoundFormatOut)
async def upsert_format(
    tournament_id: int,
    body: RoundFormatIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    t = await _tournament(db, tournament_id)
    if body.points_to_win < 1:
        raise HTTPException(422, "points_to_win must be >= 1.")
    if body.hard_cap is not None and body.hard_cap < body.points_to_win:
        raise HTTPException(422, "hard_cap must be >= points_to_win.")
    if body.games_to_win_match < 1:
        raise HTTPException(422, "games_to_win_match must be >= 1.")
    fmt = (
        await db.execute(
            select(RoundFormat).where(
                RoundFormat.tournament_id == t.id,
                RoundFormat.round_number.is_(None) if body.round_number is None
                else RoundFormat.round_number == body.round_number,
            )
        )
    ).scalar_one_or_none()
    if fmt is None:
        fmt = RoundFormat(tournament_id=t.id, round_number=body.round_number)
        db.add(fmt)
    fmt.points_to_win = body.points_to_win
    fmt.win_by_two = body.win_by_two
    fmt.hard_cap = body.hard_cap
    fmt.games_to_win_match = body.games_to_win_match
    await db.flush()
    record(db, admin, "set_format", "round_format", fmt.id, after={"round": fmt.round_number, "ptw": fmt.points_to_win})
    await db.commit()
    return fmt


@router.delete("/tournaments/{tournament_id}/formats/{round_number}")
async def delete_format(
    tournament_id: int,
    round_number: int,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
):
    t = await _tournament(db, tournament_id)
    fmt = (
        await db.execute(
            select(RoundFormat).where(
                RoundFormat.tournament_id == t.id,
                RoundFormat.round_number == round_number,
            )
        )
    ).scalar_one_or_none()
    if fmt is None:
        raise HTTPException(404, "No override for that round.")
    await db.delete(fmt)
    record(db, admin, "delete_format", "round_format", fmt.id)
    await db.commit()
    return {"ok": True}


@router.get("/audit")
async def list_audit(limit: int = 150, db: AsyncSession = Depends(get_db)):
    from ..models import AuditLog

    rows = (
        (
            await db.execute(
                select(AuditLog)
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id, "admin": r.admin_email, "action": r.action, "entity": r.entity,
            "entity_id": r.entity_id, "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]
