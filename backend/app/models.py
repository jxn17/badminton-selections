"""SQLAlchemy ORM models.

Two categories (men / women), derived from the form's Gender field. Men are
split into four balanced groups (A–D); women run as a single draw. Each group is
its own `Tournament` row with its own bracket.
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
    # Identity is the normalized phone per category (a person shouldn't be in both
    # men's and women's). Walk-ins added on the spot may share nothing, so the
    # importer/creator supplies a stable key.
    __table_args__ = (
        UniqueConstraint("dedup_key", "category", name="uq_player_dedup_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_raw: Mapped[str | None] = mapped_column(String(50))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)

    registration_number: Mapped[str | None] = mapped_column(String(60))
    year_of_study: Mapped[str | None] = mapped_column(String(40))
    experience_level: Mapped[str | None] = mapped_column(String(60))

    category: Mapped[Category] = mapped_column(Enum(Category), nullable=False, index=True)
    # Men: 'A'..'D' once grouped. Women: null (single draw).
    group_label: Mapped[str | None] = mapped_column(String(4), index=True)

    is_walkin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_note: Mapped[str | None] = mapped_column(String(300))
    # Checked in at the venue. Admin-only operational flag (not the shortlist star).
    reported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    entry_timestamp: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        UniqueConstraint("category", "group_label", name="uq_tournament_category_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[Category] = mapped_column(Enum(Category), nullable=False, index=True)
    group_label: Mapped[str | None] = mapped_column(String(4))  # 'A'..'D' for men; null for women
    status: Mapped[TournamentStatus] = mapped_column(
        Enum(TournamentStatus), default=TournamentStatus.draft, nullable=False
    )
    draw_seed: Mapped[int | None] = mapped_column(Integer)
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
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position_in_round: Mapped[int] = mapped_column(Integer, nullable=False)

    player_a_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    player_b_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    is_bye: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    retired_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    # Distinct from RET: no-show means the match never started (no partial score).
    no_show_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))

    next_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus), default=MatchStatus.pending, nullable=False
    )
    # Free-text schedule set by admins, e.g. "Sat 10:30, Court 2".
    scheduled_time: Mapped[str | None] = mapped_column(String(120))

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
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)
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
    round_number: Mapped[int | None] = mapped_column(Integer)
    points_to_win: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    win_by_two: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hard_cap: Mapped[int | None] = mapped_column(Integer)
    games_to_win_match: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    tournament: Mapped[Tournament] = relationship(back_populates="formats")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_email: Mapped[str] = mapped_column(String(200), nullable=False)  # admin's name/initials
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
