"""Pydantic v2 response/request models.

Public schemas deliberately OMIT email and phone — those must never appear on a
public page or public API response.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import Category, MatchStatus, TournamentStatus


# ---- Players (public: no PII) ----
class PlayerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    college_branch: str | None = None
    states_nationals: str | None = None
    category: Category


# ---- Games / matches ----
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
    status: TournamentStatus
    draw_seed: int | None
    bracket_size: int | None
    num_byes: int | None


class BracketOut(BaseModel):
    tournament: TournamentOut
    players: list[PlayerPublic]
    matches: list[MatchOut]
    formats: list[RoundFormatOut]


# ---- Requests ----
class GameIn(BaseModel):
    game_number: int
    score_a: int
    score_b: int


class ScoreUpdateIn(BaseModel):
    games: list[GameIn]


class RetireIn(BaseModel):
    retired_player_id: int


class RoundFormatIn(BaseModel):
    round_number: int | None = None
    points_to_win: int = 15
    win_by_two: bool = True
    hard_cap: int | None = None
    games_to_win_match: int = 1


class GenerateDrawIn(BaseModel):
    seed: int | None = None


class AdminIn(BaseModel):
    email: str
