"""Pydantic v2 request/response models.

Phone and registration number are populated ONLY for logged-in admins (the
router decides); the public bracket never carries them.
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
    reported: bool = False  # checked in at the venue (admin-only signal)
    # Admin-only (null on public responses):
    phone: str | None = None
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
    no_show_player_id: int | None = None
    next_match_id: int | None
    status: MatchStatus
    scheduled_time: str | None = None
    games: list[GameOut] = []


class RoundFormatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    round_number: int | None
    points_to_win: int
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


class SwapIn(BaseModel):
    player_x_id: int
    player_y_id: int


class WalkinIn(BaseModel):
    name: str
    phone: str = ""
    experience: str = ""
    group_label: str | None = None  # men only; ignored for women


class MatchSlotIn(BaseModel):
    """Put a player into one side of a match, or clear it back to TBD."""
    slot: str  # 'a' or 'b'
    player_id: int | None = None


class PlayerUpdateIn(BaseModel):
    """Admin correction to an entry. Any field left out is not touched.

    Category and group are deliberately absent: they decide which draw someone
    belongs in, and moving between draws has to rebuild brackets — that is what
    'Move to group' and the rebuild actions are for.
    """
    full_name: str | None = None
    phone: str | None = None
    registration_number: str | None = None
    year_of_study: str | None = None
    experience_level: str | None = None


class RoundFormatIn(BaseModel):
    round_number: int | None = None
    points_to_win: int = 21
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


class ReportIn(BaseModel):
    reported: bool


class NoShowIn(BaseModel):
    no_show_player_id: int


class ScheduleSpecificIn(BaseModel):
    """Paste any text (e.g. a WhatsApp export); phone numbers are auto-detected
    and each matched player's current match is laid onto the given window."""
    text: str
    day_label: str = ""
    start: str = "09:00"
    courts: list[str] = ["Court 1"]
    minutes_per_match: int = 8
