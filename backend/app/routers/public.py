"""Public, read-only endpoints. No auth. Phone/registration only when admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_admin_name
from ..database import get_db
from ..models import Category, Match, Player, RoundFormat, Tournament
from ..schemas import (
    BracketOut,
    GroupSummary,
    MatchOut,
    PlayerOut,
    RoundFormatOut,
    TournamentOut,
)

router = APIRouter(prefix="/api", tags=["public"])


def player_out(p: Player, include_pii: bool) -> PlayerOut:
    return PlayerOut(
        id=p.id,
        full_name=p.full_name,
        category=p.category,
        group_label=p.group_label,
        experience_level=p.experience_level,
        year_of_study=p.year_of_study,
        is_walkin=p.is_walkin,
        flagged=p.flagged,
        flag_note=p.flag_note,
        phone=(p.phone_raw if include_pii else None),
        registration_number=(p.registration_number if include_pii else None),
    )


def _parse_category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError:
        raise HTTPException(404, "Category must be 'men' or 'women'.") from None


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/groups", response_model=list[GroupSummary])
def list_groups(db: Session = Depends(get_db)):
    """All tournaments (women + men A–D) for the navbar."""
    out: list[GroupSummary] = []
    tournaments = db.query(Tournament).order_by(Tournament.category, Tournament.group_label).all()
    for t in tournaments:
        q = db.query(Player).filter(Player.category == t.category)
        if t.group_label is None:
            q = q.filter(Player.group_label.is_(None))
        else:
            q = q.filter(Player.group_label == t.group_label)
        out.append(
            GroupSummary(
                group_label=t.group_label,
                category=t.category,
                status=t.status,
                player_count=q.count(),
                bracket_size=t.bracket_size,
                num_byes=t.num_byes,
            )
        )
    return out


@router.get("/bracket", response_model=BracketOut)
def get_bracket(
    request: Request,
    category: str,
    group: str | None = None,
    db: Session = Depends(get_db),
):
    cat = _parse_category(category)
    include_pii = current_admin_name(request) is not None

    q = db.query(Tournament).filter(Tournament.category == cat)
    if cat == Category.men:
        if not group:
            raise HTTPException(400, "Men's bracket requires a group (A–D).")
        q = q.filter(Tournament.group_label == group)
    else:
        q = q.filter(Tournament.group_label.is_(None))
    tournament = q.one_or_none()

    pq = db.query(Player).filter(Player.category == cat)
    if cat == Category.men and group:
        pq = pq.filter(Player.group_label == group)
    elif cat == Category.women:
        pq = pq.filter(Player.group_label.is_(None))
    players = pq.order_by(Player.full_name).all()

    if tournament is None:
        return BracketOut(
            tournament=TournamentOut(
                id=0, category=cat, group_label=group, status="draft",
                draw_seed=None, bracket_size=None, num_byes=None,
            ),
            players=[player_out(p, include_pii) for p in players],
            matches=[],
            formats=[],
        )

    matches = (
        db.query(Match)
        .filter(Match.tournament_id == tournament.id)
        .order_by(Match.round_number, Match.position_in_round)
        .all()
    )
    formats = (
        db.query(RoundFormat)
        .filter(RoundFormat.tournament_id == tournament.id)
        .order_by(RoundFormat.round_number.nullsfirst())
        .all()
    )
    return BracketOut(
        tournament=TournamentOut.model_validate(tournament),
        players=[player_out(p, include_pii) for p in players],
        matches=[MatchOut.model_validate(m) for m in matches],
        formats=[RoundFormatOut.model_validate(f) for f in formats],
    )
