"""Assign men into 4 balanced groups (A–D) with fair distribution of strength.

Nationals/States and District players are spread evenly across the groups (snake
draft over strength tiers), so no single group is stacked — that's the "fair
chances for everyone" requirement. Within a tier the order is shuffled with the
stored seed, so which specific strong player lands in which group stays random
but the *balance* is guaranteed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .draw import fisher_yates
from .models import Category, Player

GROUP_LABELS = ["A", "B", "C", "D"]


def experience_rank(level: str | None) -> int:
    """0 = strongest. Robust to casing/extra words."""
    v = (level or "").strip().lower()
    if "national" in v or "state" in v:
        return 0
    if "district" in v or "local" in v:
        return 1
    if "school" in v:
        return 2
    if "casual" in v:
        return 3
    return 4  # beginner / no experience / unknown


def plan_groups(players: list[Player], seed: int, num_groups: int = 4) -> dict[int, str]:
    """Return {player_id: group_label}. Pure (no DB writes)."""
    # Bucket by strength tier, shuffle within each tier for fairness.
    tiers: dict[int, list[Player]] = {}
    for p in players:
        tiers.setdefault(experience_rank(p.experience_level), []).append(p)

    ordered: list[Player] = []
    for rank in sorted(tiers):
        shuffled = fisher_yates(tiers[rank], seed + rank)  # vary per tier, still reproducible
        ordered.extend(shuffled)

    # Snake draft across groups: A B C D | D C B A | A B C D ...
    assignment: dict[int, str] = {}
    for i, p in enumerate(ordered):
        row, col = divmod(i, num_groups)
        idx = col if row % 2 == 0 else (num_groups - 1 - col)
        assignment[p.id] = GROUP_LABELS[idx]
    return assignment


def assign_men_groups(db: Session, seed: int) -> dict[str, int]:
    """Assign every men's player a group_label. Returns per-group counts."""
    men = db.query(Player).filter(Player.category == Category.men).order_by(Player.id).all()
    mapping = plan_groups(men, seed)
    counts: dict[str, int] = {g: 0 for g in GROUP_LABELS}
    for p in men:
        p.group_label = mapping[p.id]
        counts[p.group_label] += 1
    db.flush()
    return counts
