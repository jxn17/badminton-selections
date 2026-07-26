import { Match, Player, RoundFormat } from "./api";

export function playerMap(players: Player[]): Map<number, Player> {
  return new Map(players.map((p) => [p.id, p]));
}

/** Resolve a match's scoring format: per-round override if present, else default. */
export function resolveFormat(formats: RoundFormat[], round: number): RoundFormat {
  const override = formats.find((f) => f.round_number === round);
  if (override) return override;
  const dflt = formats.find((f) => f.round_number === null);
  if (dflt) return dflt;
  return {
    id: -1,
    round_number: null,
    points_to_win: 15,
    win_by_two: true,
    hard_cap: null,
    games_to_win_match: 1,
  };
}

/** Max number of games a match can run (single game -> 1, best-of-3 -> 3). */
export function maxGames(fmt: RoundFormat): number {
  return Math.max(1, fmt.games_to_win_match * 2 - 1);
}

/** Human round name given the total number of rounds. */
export function roundName(round: number, totalRounds: number): string {
  const fromEnd = totalRounds - round; // 0 = final
  if (fromEnd === 0) return "Final";
  if (fromEnd === 1) return "Semifinals";
  if (fromEnd === 2) return "Quarterfinals";
  const size = 2 ** (fromEnd + 1);
  return `Round of ${size}`;
}

export function groupByRound(matches: Match[]): Map<number, Match[]> {
  const rounds = new Map<number, Match[]>();
  for (const m of matches) {
    if (!rounds.has(m.round_number)) rounds.set(m.round_number, []);
    rounds.get(m.round_number)!.push(m);
  }
  for (const list of rounds.values())
    list.sort((a, b) => a.position_in_round - b.position_in_round);
  return rounds;
}
