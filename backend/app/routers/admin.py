"""Admin (write) endpoints. Every route requires the shared access-code session."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..audit import match_snapshot, record
from ..auth import require_admin
from ..csv_import import import_csv
from ..database import get_db
from ..models import Category, Match, MatchStatus, Player, RoundFormat, Tournament, TournamentStatus
from ..scoring import (
    GameInput,
    ScoringError,
    apply_scores,
    clear_retirement,
    set_retirement,
)
from ..service import (
    add_walkin,
    move_players_to_groups,
    rebuild_men,
    rebuild_women,
    remove_player,
    swap_players,
)
from ..schemas import (
    FlagIn,
    MoveToGroupIn,
    GenerateDrawIn,
    RetireIn,
    RoundFormatIn,
    RoundFormatOut,
    ScheduleIn,
    ScoreUpdateIn,
    SwapIn,
    WalkinIn,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _match(db: Session, match_id: int) -> Match:
    m = db.get(Match, match_id)
    if m is None:
        raise HTTPException(404, "Match not found.")
    return m


def _tournament(db: Session, tournament_id: int) -> Tournament:
    t = db.get(Tournament, tournament_id)
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
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    report = import_csv(db, content)
    record(db, admin, "import_csv", "players", None, after=report.as_dict())
    db.commit()
    return report.as_dict()


@router.post("/men/rebuild")
def build_men(body: GenerateDrawIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    try:
        result = rebuild_men(db, seed=body.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record(db, admin, "rebuild_men", "tournament", None, after=result)
    db.commit()
    return result


@router.post("/women/rebuild")
def build_women(body: GenerateDrawIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    try:
        result = rebuild_women(db, seed=body.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record(db, admin, "rebuild_women", "tournament", None, after=result)
    db.commit()
    return result


@router.post("/tournaments/{tournament_id}/lock")
def lock(tournament_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    t = _tournament(db, tournament_id)
    if not t.matches:
        raise HTTPException(400, "Generate the draw before locking.")
    if t.status != TournamentStatus.draft:
        raise HTTPException(409, "Already locked.")
    t.status = TournamentStatus.locked
    t.locked_at = dt.datetime.now(dt.timezone.utc)
    record(db, admin, "lock", "tournament", t.id, after={"status": "locked"})
    db.commit()
    return {"status": t.status.value}


@router.post("/tournaments/{tournament_id}/unlock")
def unlock(tournament_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    t = _tournament(db, tournament_id)
    t.status = TournamentStatus.draft
    t.locked_at = None
    record(db, admin, "unlock", "tournament", t.id, after={"status": "draft"})
    db.commit()
    return {"status": t.status.value}


# --------------------------------------------------------------------------
# Scoring / match edits
# --------------------------------------------------------------------------
@router.put("/matches/{match_id}/score")
def update_score(match_id: int, body: ScoreUpdateIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    m = _match(db, match_id)
    before = match_snapshot(m)
    games = [GameInput(g.game_number, g.score_a, g.score_b) for g in body.games]
    try:
        apply_scores(db, m, games, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "score_edit", "match", m.id, before, match_snapshot(m))
    db.commit()
    return match_snapshot(m)


@router.post("/matches/{match_id}/retire")
def retire(match_id: int, body: RetireIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    m = _match(db, match_id)
    before = match_snapshot(m)
    try:
        set_retirement(db, m, body.retired_player_id, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "retire", "match", m.id, before, match_snapshot(m))
    db.commit()
    return match_snapshot(m)


@router.delete("/matches/{match_id}/retire")
def unretire(match_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    m = _match(db, match_id)
    before = match_snapshot(m)
    try:
        clear_retirement(db, m, admin)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "clear_retire", "match", m.id, before, match_snapshot(m))
    db.commit()
    return match_snapshot(m)


@router.post("/matches/{match_id}/reset")
def reset_match(match_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    m = _match(db, match_id)
    before = match_snapshot(m)
    if m.next_match_id is not None:
        nxt = db.get(Match, m.next_match_id)
        if nxt is not None and (nxt.status != MatchStatus.pending or nxt.winner_id is not None or nxt.games):
            raise HTTPException(409, "The next-round match has started. Reset that one first.")
        if nxt is not None:
            if m.position_in_round % 2 == 0:
                nxt.player_a_id = None
            else:
                nxt.player_b_id = None
    for g in list(m.games):
        db.delete(g)
    m.winner_id = None
    m.retired_player_id = None
    m.status = MatchStatus.pending
    record(db, admin, "reset_match", "match", m.id, before, match_snapshot(m))
    db.commit()
    return match_snapshot(m)


@router.put("/matches/{match_id}/schedule")
def set_schedule(match_id: int, body: ScheduleIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    m = _match(db, match_id)
    before = {"scheduled_time": m.scheduled_time}
    m.scheduled_time = (body.scheduled_time or "").strip() or None
    record(db, admin, "schedule", "match", m.id, before, {"scheduled_time": m.scheduled_time})
    db.commit()
    return {"id": m.id, "scheduled_time": m.scheduled_time}


# --------------------------------------------------------------------------
# Roster: flag/shortlist, swap, walk-ins
# --------------------------------------------------------------------------
@router.post("/players/{player_id}/flag")
def flag_player(player_id: int, body: FlagIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    p = db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found.")
    before = {"flagged": p.flagged, "flag_note": p.flag_note}
    p.flagged = body.flagged
    p.flag_note = (body.note or "").strip() or None
    record(db, admin, "flag_player", "player", p.id, before, {"flagged": p.flagged, "flag_note": p.flag_note})
    db.commit()
    return {"id": p.id, "flagged": p.flagged, "flag_note": p.flag_note}


@router.delete("/players/{player_id}")
def delete_player(player_id: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    try:
        result = remove_player(db, player_id)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "remove_player", "player", player_id, after=result)
    db.commit()
    return result


@router.post("/move-to-group")
def move_to_group(
    body: MoveToGroupIn,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
):
    """Bulk-move men into given groups (e.g. everyone who can only play Sunday)."""
    try:
        result = move_players_to_groups(db, body.phones, body.target_groups, Category.men)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "move_to_group", "player", None, after=result)
    db.commit()
    return result


@router.post("/tournaments/{tournament_id}/swap")
def swap(tournament_id: int, body: SwapIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    t = _tournament(db, tournament_id)
    try:
        swap_players(db, t, body.player_x_id, body.player_y_id)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "swap_players", "tournament", t.id,
           after={"x": body.player_x_id, "y": body.player_y_id})
    db.commit()
    return {"ok": True}


@router.post("/walkin/{category}")
def walkin_cat(category: str, body: WalkinIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    try:
        cat = Category(category)
    except ValueError:
        raise HTTPException(404, "Category must be 'men' or 'women'.") from None
    try:
        result = add_walkin(db, cat, body.name, body.phone, body.experience, body.group_label)
    except ScoringError as exc:
        _scoring_error(exc)
    record(db, admin, "add_walkin", "player", result["player_id"], after=result)
    db.commit()
    return result


# --------------------------------------------------------------------------
# Scoring formats (per tournament/group)
# --------------------------------------------------------------------------
@router.get("/tournaments/{tournament_id}/formats", response_model=list[RoundFormatOut])
def list_formats(tournament_id: int, db: Session = Depends(get_db)):
    t = _tournament(db, tournament_id)
    return (
        db.query(RoundFormat)
        .filter(RoundFormat.tournament_id == t.id)
        .order_by(RoundFormat.round_number.nullsfirst())
        .all()
    )


@router.put("/tournaments/{tournament_id}/formats", response_model=RoundFormatOut)
def upsert_format(tournament_id: int, body: RoundFormatIn, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    t = _tournament(db, tournament_id)
    if body.points_to_win < 1:
        raise HTTPException(422, "points_to_win must be >= 1.")
    if body.hard_cap is not None and body.hard_cap < body.points_to_win:
        raise HTTPException(422, "hard_cap must be >= points_to_win.")
    if body.games_to_win_match < 1:
        raise HTTPException(422, "games_to_win_match must be >= 1.")
    fmt = (
        db.query(RoundFormat)
        .filter(
            RoundFormat.tournament_id == t.id,
            RoundFormat.round_number.is_(None) if body.round_number is None
            else RoundFormat.round_number == body.round_number,
        )
        .one_or_none()
    )
    if fmt is None:
        fmt = RoundFormat(tournament_id=t.id, round_number=body.round_number)
        db.add(fmt)
    fmt.points_to_win = body.points_to_win
    fmt.win_by_two = body.win_by_two
    fmt.hard_cap = body.hard_cap
    fmt.games_to_win_match = body.games_to_win_match
    db.flush()
    record(db, admin, "set_format", "round_format", fmt.id, after={"round": fmt.round_number, "ptw": fmt.points_to_win})
    db.commit()
    return fmt


@router.delete("/tournaments/{tournament_id}/formats/{round_number}")
def delete_format(tournament_id: int, round_number: int, db: Session = Depends(get_db), admin: str = Depends(require_admin)):
    t = _tournament(db, tournament_id)
    fmt = (
        db.query(RoundFormat)
        .filter(RoundFormat.tournament_id == t.id, RoundFormat.round_number == round_number)
        .one_or_none()
    )
    if fmt is None:
        raise HTTPException(404, "No override for that round.")
    db.delete(fmt)
    record(db, admin, "delete_format", "round_format", fmt.id)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def list_audit(limit: int = 150, db: Session = Depends(get_db)):
    from ..models import AuditLog

    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "admin": r.admin_email, "action": r.action, "entity": r.entity,
            "entity_id": r.entity_id, "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]
