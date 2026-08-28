"""Pydantic v2 request/response models.

Phone numbers are public on bracket/search responses. Registration, shortlist,
and no-show fields are admin-only (the router decides).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import Category, MatchStatus, TournamentStatus


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    category: Category
    group_label: str | None = None
    experience_level: str | None = None
    year_of_study: str | None = None
    is_walkin: bool = False
    flagged: bool = False
    flag_note: str | None = None
    no_show: bool = False
    phone: str | None = None
    # Admin-only (null on public responses):
    registration_number: str | None = None


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    game_number: int
    score_a: int
    score_b: int


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    round_number: int
    position_in_round: int
    player_a_id: int | None
    player_b_id: int | None
    is_bye: bool
    winner_id: int | None
    retired_player_id: int | None
    next_match_id: int | None
    status: MatchStatus
    scheduled_time: str | None = None
    games: list[GameOut] = []


class RoundFormatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    round_number: int | None
    points_to_win: int
    alt_points_to_win: int | None = None
    win_by_two: bool
    hard_cap: int | None
    games_to_win_match: int


class TournamentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: Category
    group_label: str | None
    status: TournamentStatus
    draw_seed: int | None
    bracket_size: int | None
    num_byes: int | None


class BracketOut(BaseModel):
    tournament: TournamentOut
    players: list[PlayerOut]
    matches: list[MatchOut]
    formats: list[RoundFormatOut]


class GroupSummary(BaseModel):
    group_label: str | None
    category: Category
    status: TournamentStatus
    player_count: int
    bracket_size: int | None
    num_byes: int | None


# ---- Requests ----
class CodeLoginIn(BaseModel):
    code: str
    name: str = "admin"


class GameIn(BaseModel):
    game_number: int
    score_a: int
    score_b: int


class ScoreUpdateIn(BaseModel):
    games: list[GameIn]


class RetireIn(BaseModel):
    retired_player_id: int


class ScheduleIn(BaseModel):
    scheduled_time: str | None = None


class FlagIn(BaseModel):
    flagged: bool
    note: str | None = None


class NoShowIn(BaseModel):
    no_show: bool


class SwapIn(BaseModel):
    player_x_id: int
    player_y_id: int


class WalkinIn(BaseModel):
    name: str
    phone: str = ""
    experience: str = ""
    group_label: str | None = None  # men only; ignored for women


class RoundFormatIn(BaseModel):
    round_number: int | None = None
    points_to_win: int = 21
    alt_points_to_win: int | None = 11
    win_by_two: bool = True
    hard_cap: int | None = 30
    games_to_win_match: int = 1


class GenerateDrawIn(BaseModel):
    seed: int | None = None


class MoveToGroupIn(BaseModel):
    """Move a set of players (by phone) into the given men's groups."""
    phones: list[str]
    target_groups: list[str]


class ScheduleTarget(BaseModel):
    category: Category
    group: str | None = None


class ScheduleDayIn(BaseModel):
    """Lay matches onto courts across one day's playing window."""
    targets: list[ScheduleTarget]
    day_label: str = ""
    start: str = "09:00"
    end: str = "17:00"
    courts: list[str] = ["Court 1"]
    minutes_per_match: int = 12
    # Players who can't play this day — their matches are held for another day.
    unavailable_phones: list[str] = []
    # Leave already-timed matches alone (use for the second day of a split draw).
    only_unscheduled: bool = False


class ClearScheduleIn(BaseModel):
    targets: list[ScheduleTarget]
