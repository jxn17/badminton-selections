"""Public, read-only endpoints. No auth. Never exposes email or phone."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, Match, Player, RoundFormat, Tournament
from ..schemas import (
    BracketOut,
    MatchOut,
    PlayerPublic,
    RoundFormatOut,
    TournamentOut,
)

router = APIRouter(prefix="/api", tags=["public"])


def _parse_category(value: str) -> Category:
    try:
        return Category(value)
    except ValueError:
        raise HTTPException(404, "Category must be 'men' or 'women'.") from None


@router.get("/categories/{category}/players", response_model=list[PlayerPublic])
def list_players(category: str, db: Session = Depends(get_db)):
    cat = _parse_category(category)
    return (
        db.query(Player)
        .filter(Player.category == cat)
        .order_by(Player.full_name)
        .all()
    )


@router.get("/categories/{category}/bracket", response_model=BracketOut)
def get_bracket(category: str, db: Session = Depends(get_db)):
    cat = _parse_category(category)
    tournament = db.query(Tournament).filter(Tournament.category == cat).one_or_none()
    players = (
        db.query(Player).filter(Player.category == cat).order_by(Player.full_name).all()
    )

    if tournament is None:
        # No draw yet: report an empty, draft-like shell so the UI can say "not drawn".
        return BracketOut(
            tournament=TournamentOut(
                id=0, category=cat, status="draft", draw_seed=None,
                bracket_size=None, num_byes=None,
            ),
            players=[PlayerPublic.model_validate(p) for p in players],
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
        players=[PlayerPublic.model_validate(p) for p in players],
        matches=[MatchOut.model_validate(m) for m in matches],
        formats=[RoundFormatOut.model_validate(f) for f in formats],
    )
