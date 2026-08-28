"""Audit-log helpers. Every admin mutation records who/what/before/after."""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from .models import AuditLog, Game, Match


def _json_default(o):
    if isinstance(o, dt.datetime):
        return o.isoformat()
    return str(o)


def match_snapshot(match: Match) -> dict:
    """Serializable snapshot of a match's scoreable state for before/after diffs."""
    return {
        "id": match.id,
        "status": match.status.value if match.status else None,
        "winner_id": match.winner_id,
        "retired_player_id": match.retired_player_id,
        "no_show_player_id": match.no_show_player_id,
        "player_a_id": match.player_a_id,
        "player_b_id": match.player_b_id,
        "games": [
            {"game_number": g.game_number, "score_a": g.score_a, "score_b": g.score_b}
            for g in sorted(match.games, key=lambda x: x.game_number)
        ],
    }


def record(
    db: Session,
    admin_email: str,
    action: str,
    entity: str,
    entity_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_email=admin_email,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before_json=json.dumps(before, default=_json_default) if before is not None else None,
            after_json=json.dumps(after, default=_json_default) if after is not None else None,
        )
    )
