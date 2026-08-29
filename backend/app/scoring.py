"""Scoring, winner determination and bracket advancement.

The rule is deliberately simple: **whoever scored more points wins**. Scores are
never rejected for failing to reach a target, for not winning by two, or for
exceeding a cap — trials get played to whatever length the schedule allows, and
the app's job is to record what happened, not to argue with the organiser.

`RoundFormat` survives for display (the "1 game to 21" caption) and for how many
game boxes a card shows, but it no longer gates whether a scoreline is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
async def resolve_format(
    db: AsyncSession, tournament: Tournament, round_number: int
) -> RoundFormat:
    """Per-round override if one exists, else the tournament default (round=NULL).

    Falls back to a sane in-memory default (single game to 15, win-by-two) if the
    tournament has no configured formats yet.
    """
    override = (
        await db.execute(
            select(RoundFormat).where(
                RoundFormat.tournament_id == tournament.id,
                RoundFormat.round_number == round_number,
            )
        )
    ).scalar_one_or_none()
    if override is not None:
        return override
    default = (
        await db.execute(
            select(RoundFormat).where(
                RoundFormat.tournament_id == tournament.id,
                RoundFormat.round_number.is_(None),
            )
        )
    ).scalar_one_or_none()
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
    """Classify one game's scores: whoever has more points has won it.

    - 'a'/'b'     : that side scored more and wins the game
    - 'incomplete': scores are level, so there is nothing to decide yet
    - 'invalid'   : only a negative score, which can't be a real scoreline

    Deliberately unconditional. There is no target score, no win-by-two and no
    cap: a trial gets played to whatever the court agreed on and shortened all
    day as the schedule slips, so the app refusing an organiser's scoreline
    ("that isn't 21") was rejecting results that had genuinely happened. The
    format is still carried for display and for how many game boxes to show,
    but it no longer decides whether a score is allowed.
    """
    if a < 0 or b < 0:
        return GameResult("invalid", "Scores must be non-negative.")
    if a == b:
        # Includes the 0-0 of an untouched row: nobody is ahead, so nobody won.
        return GameResult("incomplete")
    return GameResult("a" if a > b else "b")


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
    # Nobody has taken the format's full number of games yet, but if one side is
    # simply ahead on games won, they're the one to put through — the same
    # "whoever is ahead advances" rule as a single game. Only a genuine tie
    # (including no games at all) leaves the match undecided.
    if wins_a > wins_b:
        return match.player_a_id, results
    if wins_b > wins_a:
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


async def _advance(db: AsyncSession, match: Match) -> None:
    if match.next_match_id is None:
        return
    nxt = await db.get(Match, match.next_match_id)
    if nxt is None:
        return
    if _slot_is_a(match):
        nxt.player_a_id = match.winner_id
    else:
        nxt.player_b_id = match.winner_id


async def _withdraw(db: AsyncSession, match: Match) -> None:
    """Remove this match's previously-advanced player from the downstream slot.

    Caller must have verified the downstream match hasn't started.
    """
    if match.next_match_id is None:
        return
    nxt = await db.get(Match, match.next_match_id)
    if nxt is None:
        return
    if _slot_is_a(match):
        nxt.player_a_id = None
    else:
        nxt.player_b_id = None


async def _guard_downstream_editable(db: AsyncSession, match: Match) -> None:
    """Block an edit that would change advancement when the next match has begun."""
    if match.next_match_id is None:
        return
    nxt = await db.get(Match, match.next_match_id)
    if _is_started(nxt):
        raise ScoringError(
            "The next-round match has already started. Reset it first before changing this result."
        )


async def apply_scores(
    db: AsyncSession, match: Match, games: list[GameInput], admin_email: str
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

    fmt = await resolve_format(db, match.tournament, match.round_number)
    new_winner, _ = _match_winner_from_games(match, fmt, games)
    old_winner = match.winner_id

    # If the decided winner changes (including won -> undecided), the old winner
    # may already be advanced. Guard the downstream match before mutating.
    if new_winner != old_winner and old_winner is not None:
        await _guard_downstream_editable(db, match)
        await _withdraw(db, match)

    # Replace stored games *through the collection* rather than with bare
    # db.delete/db.add. Sessions no longer expire objects on commit (see
    # database.py), so mutating the relationship is what keeps `match.games`
    # truthful in memory — the score snapshot returned to the browser is read
    # straight off it.
    match.games.clear()
    await db.flush()
    for g in games:
        match.games.append(
            Game(
                game_number=g.game_number,
                score_a=g.score_a,
                score_b=g.score_b,
            )
        )

    match.retired_player_id = None  # entering real scores clears any RET flag
    match.no_show_player_id = None  # ...and any no-show flag
    match.winner_id = new_winner
    if new_winner is not None:
        match.status = MatchStatus.completed
        await _advance(db, match)
    else:
        match.status = MatchStatus.in_progress if games else MatchStatus.pending

    await db.flush()
    return match


async def set_retirement(
    db: AsyncSession, match: Match, retired_player_id: int, admin_email: str
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
        await _guard_downstream_editable(db, match)
        await _withdraw(db, match)

    match.retired_player_id = retired_player_id
    match.no_show_player_id = None
    match.winner_id = winner
    match.status = MatchStatus.completed
    await _advance(db, match)
    await db.flush()
    return match


async def set_no_show(
    db: AsyncSession, match: Match, no_show_player_id: int, admin_email: str
) -> Match:
    """Mark a player as not having shown up: the opponent wins immediately.

    Distinct from RET — a no-show means the match never started at all, so any
    previously-entered partial score is discarded (RET keeps it). Overrides the
    win-by-two rule the same way RET does.
    """
    if match.is_bye:
        raise ScoringError("Bye matches are decided automatically.")
    if match.player_a_id is None or match.player_b_id is None:
        raise ScoringError("Both players must be present to record a no-show.")
    if no_show_player_id not in (match.player_a_id, match.player_b_id):
        raise ScoringError("That player is not part of this match.")

    winner = (
        match.player_b_id if no_show_player_id == match.player_a_id else match.player_a_id
    )
    if winner != match.winner_id and match.winner_id is not None:
        await _guard_downstream_editable(db, match)
        await _withdraw(db, match)

    match.games.clear()
    await db.flush()

    match.retired_player_id = None
    match.no_show_player_id = no_show_player_id
    match.winner_id = winner
    match.status = MatchStatus.completed
    await _advance(db, match)
    await db.flush()
    return match


async def clear_no_show(db: AsyncSession, match: Match, admin_email: str) -> Match:
    """Undo a no-show: back to pending (no games were kept to recompute from)."""
    return await apply_scores(db, match, [], admin_email)


async def clear_retirement(db: AsyncSession, match: Match, admin_email: str) -> Match:
    """Un-retire: recompute the result from the stored game scores."""
    games = [
        GameInput(game_number=g.game_number, score_a=g.score_a, score_b=g.score_b)
        for g in match.games
    ]
    return await apply_scores(db, match, games, admin_email)
