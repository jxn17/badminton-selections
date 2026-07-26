"""SQLAlchemy ORM models.

Two independent tournaments (men / women) run in parallel. Everything is scoped
by `category`. See the module docstrings in draw.py and scoring.py for the logic
that operates over these tables.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Category(str, enum.Enum):
    men = "men"
    women = "women"


class TournamentStatus(str, enum.Enum):
    draft = "draft"
    locked = "locked"
    completed = "completed"


class MatchStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Player(Base):
    __tablename__ = "players"
    # A person is unique per category by their normalized phone. The same human
    # could (but shouldn't) enter both draws, so men/women are independent.
    __table_args__ = (
        UniqueConstraint("phone_normalized", "category", name="uq_player_phone_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    college_branch: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone_raw: Mapped[str] = mapped_column(String(50), nullable=False)
    phone_normalized: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    states_nationals: Mapped[str | None] = mapped_column(String(50))
    category: Mapped[Category] = mapped_column(Enum(Category), nullable=False, index=True)
    entry_timestamp: Mapped[str | None] = mapped_column(String(64))  # raw form timestamp, for tie-break
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[Category] = mapped_column(Enum(Category), nullable=False, unique=True)
    status: Mapped[TournamentStatus] = mapped_column(
        Enum(TournamentStatus), default=TournamentStatus.draft, nullable=False
    )
    draw_seed: Mapped[int | None] = mapped_column(Integer)  # RNG seed used, for reproducibility
    bracket_size: Mapped[int | None] = mapped_column(Integer)
    num_byes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    matches: Mapped[list[Match]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    formats: Mapped[list[RoundFormat]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = first round
    position_in_round: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based

    player_a_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    player_b_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    is_bye: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    retired_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))

    # Advancement wiring: winner of this match flows into next_match_id.
    next_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), default=MatchStatus.pending, nullable=False
    )

    tournament: Mapped[Tournament] = relationship(back_populates="matches")
    player_a: Mapped[Player | None] = relationship(foreign_keys=[player_a_id])
    player_b: Mapped[Player | None] = relationship(foreign_keys=[player_b_id])
    winner: Mapped[Player | None] = relationship(foreign_keys=[winner_id])
    games: Mapped[list[Game]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Game.game_number"
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    score_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_b: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    match: Mapped[Match] = relationship(back_populates="games")


class RoundFormat(Base):
    """Scoring rules. round_number NULL = tournament default; a value = per-round override."""

    __tablename__ = "round_formats"
    __table_args__ = (
        UniqueConstraint("tournament_id", "round_number", name="uq_format_tournament_round"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int | None] = mapped_column(Integer)  # NULL = default
    points_to_win: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    win_by_two: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hard_cap: Mapped[int | None] = mapped_column(Integer)  # NULL = no cap
    games_to_win_match: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    tournament: Mapped[Tournament] = relationship(back_populates="formats")


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    added_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_email: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
