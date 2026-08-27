"""Public, read-only endpoints. No auth. Phone/registration only when admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

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
    # include_pii is true only for signed-in admins. Phone, registration AND the
    # shortlist flag are all admin-only — never exposed to the public.
    return PlayerOut(
        id=p.id,
        full_name=p.full_name,
        category=p.category,
        group_label=p.group_label,
        experience_level=p.experience_level,
        year_of_study=p.year_of_study,
        is_walkin=p.is_walkin,
        flagged=(p.flagged if include_pii else False),
        flag_note=(p.flag_note if include_pii else None),
        # Normalized = clean last-10-digits (drops +91 / spaces / leading 0).
        phone=(p.phone_normalized if include_pii else None),
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


def _round_name(round_number: int, bracket_size: int | None) -> str:
    if not bracket_size:
        return f"Round {round_number}"
    total = max(1, bracket_size.bit_length() - 1)  # log2(bracket_size)
    from_end = total - round_number
    if from_end == 0:
        return "Final"
    if from_end == 1:
        return "Semifinal"
    if from_end == 2:
        return "Quarterfinal"
    return f"Round of {2 ** (from_end + 1)}"


@router.get("/search")
def search_players(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Find players by name; return their group, opponent(s), and match time(s)."""
    include_pii = current_admin_name(request) is not None
    q = (q or "").strip()
    if len(q) < 2:
        return []

    players = (
        db.query(Player)
        .filter(Player.full_name.ilike(f"%{q}%"))
        .order_by(Player.full_name)
        .limit(40)
        .all()
    )

    # Index tournaments by (category, group_label) and cache names for opponents.
    tournaments = {(t.category, t.group_label): t for t in db.query(Tournament).all()}
    name_of = {p.id: p.full_name for p in db.query(Player).all()}

    # One Match query for every found player, instead of one query per player
    # (was an N+1 that scaled with the number of search results).
    tournament_ids = {t.id for t in tournaments.values()}
    player_ids = {p.id for p in players}
    all_matches = (
        db.query(Match)
        .filter(
            Match.tournament_id.in_(tournament_ids),
            (Match.player_a_id.in_(player_ids)) | (Match.player_b_id.in_(player_ids)),
        )
        .order_by(Match.round_number)
        .all()
        if tournament_ids and player_ids
        else []
    )
    matches_by_player: dict[int, list[Match]] = {}
    for m in all_matches:
        for pid in (m.player_a_id, m.player_b_id):
            if pid in player_ids:
                matches_by_player.setdefault(pid, []).append(m)

    results = []
    for p in players:
        t = tournaments.get((p.category, p.group_label))
        match_infos = []
        if t is not None:
            matches = matches_by_player.get(p.id, [])
            for m in matches:
                opp_id = m.player_b_id if m.player_a_id == p.id else m.player_a_id
                if m.is_bye:
                    opponent = "Bye"
                elif opp_id is None:
                    opponent = "TBD"
                else:
                    opponent = name_of.get(opp_id, "?")
                result = None
                if m.winner_id is not None:
                    result = "won" if m.winner_id == p.id else "lost"
                match_infos.append(
                    {
                        "match_id": m.id,
                        "round_number": m.round_number,
                        "round_name": _round_name(m.round_number, t.bracket_size),
                        "opponent": opponent,
                        "scheduled_time": m.scheduled_time,
                        "status": m.status.value,
                        "is_bye": m.is_bye,
                        "result": result,
                    }
                )
        results.append(
            {
                "id": p.id,
                "full_name": p.full_name,
                "category": p.category.value,
                "group_label": p.group_label,
                "experience_level": p.experience_level,
                "phone": p.phone_normalized if include_pii else None,
                "matches": match_infos,
            }
        )
    return results


@router.get("/flagged", response_model=list[PlayerOut])
def flagged_players(request: Request, db: Session = Depends(get_db)):
    """All ⭐ shortlisted players. Admin-only — the shortlist is not public."""
    if current_admin_name(request) is None:
        raise HTTPException(401, "Admin login required.")
    include_pii = True
    ps = (
        db.query(Player)
        .filter(Player.flagged.is_(True))
        .order_by(Player.category, Player.group_label.nullsfirst(), Player.full_name)
        .all()
    )
    return [player_out(p, include_pii) for p in ps]


@router.get("/groups", response_model=list[GroupSummary])
def list_groups(db: Session = Depends(get_db)):
    """All tournaments (women + men A–D) for the navbar.

    Two queries total (not one .count() per tournament) — this is on the hot
    path (it reloads after every admin action), so N+1 here is felt directly.
    """
    tournaments = db.query(Tournament).order_by(Tournament.category, Tournament.group_label).all()
    counts_by_key = {
        (cat, grp): cnt
        for cat, grp, cnt in db.query(
            Player.category, Player.group_label, func.count(Player.id)
        ).group_by(Player.category, Player.group_label)
    }
    return [
        GroupSummary(
            group_label=t.group_label,
            category=t.category,
            status=t.status,
            player_count=counts_by_key.get((t.category, t.group_label), 0),
            bracket_size=t.bracket_size,
            num_byes=t.num_byes,
        )
        for t in tournaments
    ]


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

    # selectinload pulls every match's games in ONE extra query. Without it
    # SQLAlchemy lazy-loads games per match (~63 extra round-trips per bracket),
    # which is barely noticeable locally but seconds of latency against a remote DB.
    matches = (
        db.query(Match)
        .options(selectinload(Match.games))
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
