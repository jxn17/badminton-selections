import { Match, Player, RoundFormat } from "./api";

export function playerMap(players: Player[]): Map<number, Player> {
  return new Map(players.map((p) => [p.id, p]));
}

export function resolveFormat(formats: RoundFormat[], round: number): RoundFormat {
  const override = formats.find((f) => f.round_number === round);
  if (override) return override;
  const dflt = formats.find((f) => f.round_number === null);
  if (dflt) return dflt;
  return {
    id: -1,
    round_number: null,
    points_to_win: 21,
    alt_points_to_win: 11,
    win_by_two: true,
    hard_cap: 30,
    games_to_win_match: 1,
  };
}

export function maxGames(fmt: RoundFormat): number {
  return Math.max(1, fmt.games_to_win_match * 2 - 1);
}

export function roundName(round: number, totalRounds: number): string {
  const fromEnd = totalRounds - round;
  if (fromEnd === 0) return "Final";
  if (fromEnd === 1) return "Semifinals";
  if (fromEnd === 2) return "Quarterfinals";
  const size = 2 ** (fromEnd + 1);
  return `Round of ${size}`;
}

export function roundNameShort(round: number, totalRounds: number): string {
  const fromEnd = totalRounds - round;
  if (fromEnd === 0) return "Final";
  if (fromEnd === 1) return "SF";
  if (fromEnd === 2) return "QF";
  return `R${2 ** (fromEnd + 1)}`;
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

/** Short experience tag for a chip. */
export function expTag(level: string | null): { label: string; cls: string } | null {
  const v = (level || "").toLowerCase();
  if (v.includes("national") || v.includes("state"))
    return { label: "Nat/State", cls: "bg-red-100 text-red-700" };
  if (v.includes("district") || v.includes("local"))
    return { label: "District", cls: "bg-orange-100 text-orange-700" };
  if (v.includes("school")) return { label: "School", cls: "bg-sky-100 text-sky-700" };
  if (v.includes("casual")) return { label: "Casual", cls: "bg-slate-100 text-slate-600" };
  if (v.includes("beginner") || v.includes("no experience"))
    return { label: "Beginner", cls: "bg-slate-100 text-slate-500" };
  return null;
}
