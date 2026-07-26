"""Admin (write) endpoints. Every route depends on `require_admin` and audits."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..audit import match_snapshot, record
from ..auth import require_admin
from ..csv_import import import_csv
from ..database import get_db
from ..draw import generate_draw
from ..models import (
    Admin,
    Category,
    Match,
    MatchStatus,
    RoundFormat,
    Tournament,
    TournamentStatus,
)
from ..scoring import GameInput, ScoringError, apply_scores, clear_retirement, set_retirement
from ..schemas import (
    AdminIn,
    GenerateDrawIn,
    RetireIn,
    RoundFormatIn,
    RoundFormatOut,
    ScoreUpdateIn,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _parse_category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError:
        raise HTTPException(404, "Category must be 'men' or 'women'.") from None


def _get_or_create_tournament(db: Session, cat: Category) -> Tournament:
    t = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    if t is None:
        t = Tournament(category=cat, status=TournamentStatus.draft)
        db.add(t)
        db.flush()
        # Seed a sensible default format: single game to 15, win-by-two, no cap.
        db.add(
            RoundFormat(
                tournament_id=t.id,
                round_number=None,
                points_to_win=15,
                win_by_two=True,
                hard_cap=None,
                games_to_win_match=1,
            )
        )
        db.flush()
    return t


# --------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------
@router.post("/import")
async def import_entries(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")  # tolerate a BOM from Excel/Sheets exports
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    report = import_csv(db, content)
    record(db, admin_email, "import_csv", "players", None, after=report.as_dict())
    db.commit()
    return report.as_dict()


# --------------------------------------------------------------------------
# Draw generation / lock
# --------------------------------------------------------------------------
@router.post("/{category}/draw")
def make_draw(
    category: str,
    body: GenerateDrawIn,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    cat = _parse_category(category)
    t = _get_or_create_tournament(db, cat)
    if t.status != TournamentStatus.draft:
        raise HTTPException(409, "Draw is locked; regeneration is only allowed while draft.")
    try:
        generate_draw(db, t, seed=body.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record(
        db, admin_email, "generate_draw", "tournament", t.id,
        after={"seed": t.draw_seed, "bracket_size": t.bracket_size, "num_byes": t.num_byes},
    )
    db.commit()
    return {"seed": t.draw_seed, "bracket_size": t.bracket_size, "num_byes": t.num_byes}


@router.post("/{category}/lock")
def lock_draw(
    category: str,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    cat = _parse_category(category)
    t = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    if t is None or not t.matches:
        raise HTTPException(400, "Generate a draw before locking.")
    if t.status != TournamentStatus.draft:
        raise HTTPException(409, "Tournament is already locked.")
    import datetime as dt

    t.status = TournamentStatus.locked
    t.locked_at = dt.datetime.now(dt.timezone.utc)
    record(db, admin_email, "lock_draw", "tournament", t.id, after={"status": "locked"})
    db.commit()
    return {"status": t.status.value}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def _load_match(db: Session, category: str, match_id: int) -> Match:
    cat = _parse_category(category)
    t = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    match = db.get(Match, match_id)
    if match is None or t is None or match.tournament_id != t.id:
        raise HTTPException(404, "Match not found in this category.")
    return match


@router.put("/{category}/matches/{match_id}/score")
def update_score(
    category: str,
    match_id: int,
    body: ScoreUpdateIn,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    match = _load_match(db, category, match_id)
    before = match_snapshot(match)
    games = [GameInput(g.game_number, g.score_a, g.score_b) for g in body.games]
    try:
        apply_scores(db, match, games, admin_email)
    except ScoringError as exc:
        raise HTTPException(422, detail={"message": exc.message, "game_number": exc.game_number})
    record(db, admin_email, "score_edit", "match", match.id, before, match_snapshot(match))
    db.commit()
    return match_snapshot(match)


@router.post("/{category}/matches/{match_id}/retire")
def retire(
    category: str,
    match_id: int,
    body: RetireIn,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    match = _load_match(db, category, match_id)
    before = match_snapshot(match)
    try:
        set_retirement(db, match, body.retired_player_id, admin_email)
    except ScoringError as exc:
        raise HTTPException(422, detail={"message": exc.message, "game_number": exc.game_number})
    record(db, admin_email, "retire", "match", match.id, before, match_snapshot(match))
    db.commit()
    return match_snapshot(match)


@router.delete("/{category}/matches/{match_id}/retire")
def unretire(
    category: str,
    match_id: int,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    match = _load_match(db, category, match_id)
    before = match_snapshot(match)
    try:
        clear_retirement(db, match, admin_email)
    except ScoringError as exc:
        raise HTTPException(422, detail={"message": exc.message, "game_number": exc.game_number})
    record(db, admin_email, "clear_retire", "match", match.id, before, match_snapshot(match))
    db.commit()
    return match_snapshot(match)


@router.post("/{category}/matches/{match_id}/reset")
def reset_match(
    category: str,
    match_id: int,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    """Clear a match's result so an upstream correction can re-advance into it.

    Only allowed when this match itself has no *started* downstream match beyond
    it; it removes games, winner and RET, and withdraws its advanced player.
    """
    match = _load_match(db, category, match_id)
    before = match_snapshot(match)

    # Withdraw whatever this match pushed downstream, if that match hasn't started.
    if match.next_match_id is not None:
        nxt = db.get(Match, match.next_match_id)
        if nxt is not None and (
            nxt.status != MatchStatus.pending or nxt.winner_id is not None or nxt.games
        ):
            raise HTTPException(
                409, "The next-round match has started. Reset that one first."
            )
        if nxt is not None:
            if match.position_in_round % 2 == 0:
                nxt.player_a_id = None
            else:
                nxt.player_b_id = None

    for g in list(match.games):
        db.delete(g)
    match.winner_id = None
    match.retired_player_id = None
    match.status = MatchStatus.pending
    record(db, admin_email, "reset_match", "match", match.id, before, match_snapshot(match))
    db.commit()
    return match_snapshot(match)


# --------------------------------------------------------------------------
# Scoring formats
# --------------------------------------------------------------------------
@router.get("/{category}/formats", response_model=list[RoundFormatOut])
def list_formats(category: str, db: Session = Depends(get_db)):
    cat = _parse_category(category)
    t = _get_or_create_tournament(db, cat)
    db.commit()
    return (
        db.query(RoundFormat)
        .filter(RoundFormat.tournament_id == t.id)
        .order_by(RoundFormat.round_number.nullsfirst())
        .all()
    )


@router.put("/{category}/formats", response_model=RoundFormatOut)
def upsert_format(
    category: str,
    body: RoundFormatIn,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    cat = _parse_category(category)
    t = _get_or_create_tournament(db, cat)
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
            RoundFormat.round_number.is_(body.round_number)
            if body.round_number is None
            else RoundFormat.round_number == body.round_number,
        )
        .one_or_none()
    )
    before = None
    if fmt is None:
        fmt = RoundFormat(tournament_id=t.id, round_number=body.round_number)
        db.add(fmt)
    else:
        before = {"points_to_win": fmt.points_to_win, "win_by_two": fmt.win_by_two}
    fmt.points_to_win = body.points_to_win
    fmt.win_by_two = body.win_by_two
    fmt.hard_cap = body.hard_cap
    fmt.games_to_win_match = body.games_to_win_match
    db.flush()
    record(db, admin_email, "set_format", "round_format", fmt.id, before,
           {"round_number": fmt.round_number, "points_to_win": fmt.points_to_win})
    db.commit()
    return fmt


@router.delete("/{category}/formats/{round_number}")
def delete_format_override(
    category: str,
    round_number: int,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    cat = _parse_category(category)
    t = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    if t is None:
        raise HTTPException(404, "No tournament for this category.")
    fmt = (
        db.query(RoundFormat)
        .filter(RoundFormat.tournament_id == t.id, RoundFormat.round_number == round_number)
        .one_or_none()
    )
    if fmt is None:
        raise HTTPException(404, "No override for that round.")
    db.delete(fmt)
    record(db, admin_email, "delete_format", "round_format", fmt.id)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Admin whitelist management
# --------------------------------------------------------------------------
@router.get("/admins")
def list_admins(db: Session = Depends(get_db)):
    return [
        {"id": a.id, "email": a.email, "added_by": a.added_by}
        for a in db.query(Admin).order_by(Admin.email).all()
    ]


@router.post("/admins")
def add_admin(
    body: AdminIn,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(422, "Email required.")
    if db.query(Admin).filter(Admin.email == email).one_or_none():
        raise HTTPException(409, "Already an admin.")
    admin = Admin(email=email, added_by=admin_email)
    db.add(admin)
    record(db, admin_email, "add_admin", "admin", None, after={"email": email})
    db.commit()
    return {"id": admin.id, "email": admin.email}


@router.get("/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db)):
    from ..models import AuditLog

    rows = (
        db.query(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit).all()
    )
    return [
        {
            "id": r.id,
            "admin_email": r.admin_email,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "before_json": r.before_json,
            "after_json": r.after_json,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]


@router.delete("/admins/{admin_id}")
def remove_admin(
    admin_id: int,
    db: Session = Depends(get_db),
    admin_email: str = Depends(require_admin),
):
    admin = db.get(Admin, admin_id)
    if admin is None:
        raise HTTPException(404, "Admin not found.")
    if admin.email == admin_email:
        raise HTTPException(400, "You cannot remove yourself.")
    record(db, admin_email, "remove_admin", "admin", admin.id, before={"email": admin.email})
    db.delete(admin)
    db.commit()
    return {"ok": True}
