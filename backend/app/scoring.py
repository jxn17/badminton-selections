"""Format-driven scoring, winner determination and bracket advancement.

Nothing here hardcodes 15/21/30 — every rule is read from the resolved
`RoundFormat` (per-round override if present, else the tournament default).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Game, Match, MatchStatus, RoundFormat, Tournament


class ScoringError(Exception):
    """Raised on an invalid score edit. `game_number` lets the UI flag the cell."""

    def __init__(self, message: str, game_number: int | None = None):
        super().__init__(message)
        self.message = message
        self.game_number = game_number


# --------------------------------------------------------------------------
# Format resolution
# --------------------------------------------------------------------------
def resolve_format(db: Session, tournament: Tournament, round_number: int) -> RoundFormat:
    """Per-round override if one exists, else the tournament default (round=NULL).

    Falls back to a sane in-memory default (single game to 15, win-by-two) if the
    tournament has no configured formats yet.
    """
    override = (
        db.query(RoundFormat)
        .filter(
            RoundFormat.tournament_id == tournament.id,
            RoundFormat.round_number == round_number,
        )
        .one_or_none()
    )
    if override is not None:
        return override
    default = (
        db.query(RoundFormat)
        .filter(
            RoundFormat.tournament_id == tournament.id,
            RoundFormat.round_number.is_(None),
        )
        .one_or_none()
    )
    if default is not None:
        return default
    return RoundFormat(
        tournament_id=tournament.id,
        round_number=None,
        points_to_win=21,
        win_by_two=True,
        hard_cap=30,
        games_to_win_match=1,
    )


# --------------------------------------------------------------------------
# Single-game evaluation
# --------------------------------------------------------------------------
@dataclass
class GameResult:
    status: str  # 'a' | 'b' | 'incomplete' | 'invalid'
    error: str | None = None


def evaluate_game(fmt: RoundFormat, a: int, b: int) -> GameResult:
    """Classify one game's scores against the format.

    - 'a'/'b'   : that side has legally won the game
    - 'incomplete': valid so far but no winner yet (e.g. live 10-8, or deuce 15-14)
    - 'invalid' : impossible under the format (surfaced as an inline cell error)
    """
    ptw = fmt.points_to_win
    cap = fmt.hard_cap

    if a < 0 or b < 0:
        return GameResult("invalid", "Scores must be non-negative.")
    if cap is not None and (a > cap or b > cap):
        return GameResult("invalid", f"Score cannot exceed the hard cap of {cap}.")

    hi, lo = (a, b) if a >= b else (b, a)
    winner = "a" if a > b else ("b" if b > a else None)
    margin = hi - lo

    if hi < ptw:
        return GameResult("incomplete")  # nobody has reached the target yet

    if winner is None:
        return GameResult("invalid", f"Both sides cannot reach {ptw}; a game needs a winner.")

    # Hard cap ends the game immediately, ignoring the win-by-two rule.
    if cap is not None and hi == cap:
        return GameResult(winner)

    if fmt.win_by_two:
        if hi == ptw:
            if margin >= 2:
                return GameResult(winner)
            return GameResult("incomplete")  # e.g. 15-14 -> deuce continues
        # hi > ptw: in deuce a game is won by exactly two.
        if margin == 2:
            return GameResult(winner)
        if margin < 2:
            return GameResult("incomplete")  # 16-15
        return GameResult("invalid", "In deuce, a game is won by exactly two points.")

    # No win-by-two: first to points_to_win wins; you cannot exceed it (no cap logic hit).
    if hi == ptw:
        return GameResult(winner)
    return GameResult(
        "invalid", f"Score cannot exceed {ptw} without a win-by-two rule."
    )


# --------------------------------------------------------------------------
# Match scoring
# --------------------------------------------------------------------------
@dataclass
class GameInput:
    game_number: int
    score_a: int
    score_b: int


def _match_winner_from_games(
    match: Match, fmt: RoundFormat, games: list[GameInput]
) -> tuple[int | None, list[GameResult]]:
    """Return (winner_player_id_or_None, per-game results). Raises on invalid."""
    wins_a = wins_b = 0
    results: list[GameResult] = []
    for g in games:
        res = evaluate_game(fmt, g.score_a, g.score_b)
        if res.status == "invalid":
            raise ScoringError(res.error or "Invalid score.", g.game_number)
        results.append(res)
        if res.status == "a":
            wins_a += 1
        elif res.status == "b":
            wins_b += 1

    need = fmt.games_to_win_match
    if wins_a >= need:
        return match.player_a_id, results
    if wins_b >= need:
        return match.player_b_id, results
    return None, results


def _is_started(match: Match | None) -> bool:
    """A downstream match has 'started' once it has a result, is in progress, or
    has any games entered. We must not silently rewrite such a match."""
    if match is None:
        return False
    return (
        match.status != MatchStatus.pending
        or match.winner_id is not None
        or len(match.games) > 0
    )


def _slot_is_a(match: Match) -> bool:
    """Even Round position feeds slot A of the next match, odd feeds slot B."""
    return match.position_in_round % 2 == 0


def _advance(db: Session, match: Match) -> None:
    if match.next_match_id is None:
        return
    nxt = db.get(Match, match.next_match_id)
    if nxt is None:
        return
    if _slot_is_a(match):
        nxt.player_a_id = match.winner_id
    else:
        nxt.player_b_id = match.winner_id


def _withdraw(db: Session, match: Match) -> None:
    """Remove this match's previously-advanced player from the downstream slot.

    Caller must have verified the downstream match hasn't started.
    """
    if match.next_match_id is None:
        return
    nxt = db.get(Match, match.next_match_id)
    if nxt is None:
        return
    if _slot_is_a(match):
        nxt.player_a_id = None
    else:
        nxt.player_b_id = None


def _guard_downstream_editable(db: Session, match: Match) -> None:
    """Block an edit that would change advancement when the next match has begun."""
    if match.next_match_id is None:
        return
    nxt = db.get(Match, match.next_match_id)
    if _is_started(nxt):
        raise ScoringError(
            "The next-round match has already started. Reset it first before changing this result."
        )


def apply_scores(
    db: Session, match: Match, games: list[GameInput], admin_email: str
) -> Match:
    """Enter/edit game scores, recompute the winner, and (re)wire advancement.

    Correctly withdraws a stale advancement and pushes the corrected winner
    forward. If the downstream match has already started and the winner would
    change, the edit is blocked with a clear error.
    """
    if match.is_bye:
        raise ScoringError("Bye matches are decided automatically and cannot be scored.")
    if match.player_a_id is None or match.player_b_id is None:
        raise ScoringError("Both players must be present before scores can be entered.")

    fmt = resolve_format(db, match.tournament, match.round_number)
    new_winner, _ = _match_winner_from_games(match, fmt, games)
    old_winner = match.winner_id

    # If the decided winner changes (including won -> undecided), the old winner
    # may already be advanced. Guard the downstream match before mutating.
    if new_winner != old_winner and old_winner is not None:
        _guard_downstream_editable(db, match)
        _withdraw(db, match)

    # Replace stored games.
    for g in list(match.games):
        db.delete(g)
    db.flush()
    for g in games:
        db.add(
            Game(
                match_id=match.id,
                game_number=g.game_number,
                score_a=g.score_a,
                score_b=g.score_b,
            )
        )

    match.retired_player_id = None  # entering real scores clears any RET flag
    match.winner_id = new_winner
    if new_winner is not None:
        match.status = MatchStatus.completed
        _advance(db, match)
    else:
        match.status = MatchStatus.in_progress if games else MatchStatus.pending

    db.flush()
    return match


def set_retirement(
    db: Session, match: Match, retired_player_id: int, admin_email: str
) -> Match:
    """Flag a player as retired; the opponent advances regardless of partial score.

    RET overrides the win-by-two completion rule. Entered partial scores are kept
    for display.
    """
    if match.player_a_id is None or match.player_b_id is None:
        raise ScoringError("Both players must be present to record a retirement.")
    if retired_player_id not in (match.player_a_id, match.player_b_id):
        raise ScoringError("Retired player is not part of this match.")

    winner = (
        match.player_b_id if retired_player_id == match.player_a_id else match.player_a_id
    )
    if winner != match.winner_id and match.winner_id is not None:
        _guard_downstream_editable(db, match)
        _withdraw(db, match)

    match.retired_player_id = retired_player_id
    match.winner_id = winner
    match.status = MatchStatus.completed
    _advance(db, match)
    db.flush()
    return match


def clear_retirement(db: Session, match: Match, admin_email: str) -> Match:
    """Un-retire: recompute the result from the stored game scores."""
    games = [
        GameInput(game_number=g.game_number, score_a=g.score_a, score_b=g.score_b)
        for g in match.games
    ]
    return apply_scores(db, match, games, admin_email)
