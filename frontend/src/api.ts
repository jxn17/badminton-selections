// Typed API client. Requests send credentials so the admin session cookie rides
// along. Read endpoints are public; /admin/* require an admin session.

export type Category = "men" | "women";

export interface Player {
  id: number;
  full_name: string;
  category: Category;
  group_label: string | null;
  experience_level: string | null;
  year_of_study: string | null;
  is_walkin: boolean;
  flagged: boolean;
  flag_note: string | null;
  reported: boolean; // checked in at the venue (admin-only signal)
  struck: boolean; // crossed off the draw (admin-only signal)
  phone: string | null; // admin-only; null for public
  registration_number: string | null;
}

export interface Game {
  game_number: number;
  score_a: number;
  score_b: number;
}

export type MatchStatus = "pending" | "in_progress" | "completed";

export interface Match {
  id: number;
  round_number: number;
  position_in_round: number;
  player_a_id: number | null;
  player_b_id: number | null;
  is_bye: boolean;
  winner_id: number | null;
  retired_player_id: number | null;
  no_show_player_id: number | null;
  next_match_id: number | null;
  status: MatchStatus;
  scheduled_time: string | null;
  games: Game[];
}

export interface RoundFormat {
  id: number;
  round_number: number | null;
  points_to_win: number;
  win_by_two: boolean;
  hard_cap: number | null;
  games_to_win_match: number;
}

export interface Tournament {
  id: number;
  category: Category;
  group_label: string | null;
  status: "draft" | "locked" | "completed";
  draw_seed: number | null;
  bracket_size: number | null;
  num_byes: number | null;
}

export interface Bracket {
  tournament: Tournament;
  players: Player[];
  matches: Match[];
  formats: RoundFormat[];
}

export interface GroupSummary {
  group_label: string | null;
  category: Category;
  status: "draft" | "locked" | "completed";
  player_count: number;
  bracket_size: number | null;
  num_byes: number | null;
}

export interface Me {
  is_admin: boolean;
  name: string | null;
}

export interface SearchMatch {
  match_id: number;
  round_number: number;
  round_name: string;
  opponent: string;
  scheduled_time: string | null;
  status: MatchStatus;
  is_bye: boolean;
  result: "won" | "lost" | null;
}

export interface SearchResult {
  id: number;
  full_name: string;
  category: Category;
  group_label: string | null;
  experience_level: string | null;
  year_of_study: string | null;
  phone: string | null;
  registration_number: string | null; // admin-only, like phone
  reported: boolean;
  struck: boolean;
  matches: SearchMatch[];
}

/** The correctable fields of an entry. Omit one to leave it untouched. */
export interface PlayerEdit {
  full_name?: string;
  phone?: string;
  registration_number?: string;
  year_of_study?: string;
  experience_level?: string;
}

/** Where the bracket should jump to after a search hit: the group that holds
 * the tie, the tie itself, and the player who was searched for (so their name
 * can be picked out inside the card). */
export interface BracketFocus {
  matchId: number;
  playerId: number;
  /** Bumped on every pick so re-selecting the same tie re-triggers the jump. */
  nonce: number;
}

/** The match a player is "on" right now: their earliest undecided tie, falling
 * back to the last one they played if their run is over. */
export function currentMatch(r: SearchResult): SearchMatch | null {
  if (r.matches.length === 0) return null;
  const byRound = [...r.matches].sort((a, b) => a.round_number - b.round_number);
  return byRound.find((m) => m.result === null && !m.is_bye) ?? byRound[byRound.length - 1];
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function req<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  me: () => req<Me>("/api/auth/me"),
  codeLogin: (code: string, name: string) =>
    req<{ ok: boolean; name: string }>("/api/auth/code-login", {
      method: "POST",
      body: JSON.stringify({ code, name }),
    }),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  groups: () => req<GroupSummary[]>("/api/groups"),
  flagged: () => req<Player[]>("/api/flagged"),
  search: (q: string) => req<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`),
  moveToGroup: (phones: string[], target_groups: string[]) =>
    req<any>("/api/admin/move-to-group", {
      method: "POST",
      body: JSON.stringify({ phones, target_groups }),
    }),
  scheduleDay: (body: {
    targets: { category: Category; group: string | null }[];
    day_label: string;
    start: string;
    end: string;
    courts: string[];
    minutes_per_match: number;
    unavailable_phones?: string[];
    only_unscheduled?: boolean;
  }) => req<any>("/api/admin/schedule-day", { method: "POST", body: JSON.stringify(body) }),
  clearSchedule: (targets: { category: Category; group: string | null }[]) =>
    req<any>("/api/admin/clear-schedule", { method: "POST", body: JSON.stringify({ targets }) }),
  removePlayer: (id: number) => req<{ removed: number; name: string }>(`/api/admin/players/${id}`, { method: "DELETE" }),
  updatePlayer: (id: number, body: PlayerEdit) =>
    req<{
      id: number;
      full_name: string;
      phone: string | null;
      registration_number: string | null;
      year_of_study: string | null;
      experience_level: string | null;
    }>(`/api/admin/players/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  bracket: (category: Category, group?: string | null) => {
    const q = new URLSearchParams({ category });
    if (group) q.set("group", group);
    return req<Bracket>(`/api/bracket?${q.toString()}`);
  },

  importCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    // Fail loudly after 60s rather than spinning forever if the request stalls.
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 60000);
    try {
      const res = await fetch("/api/admin/import", {
        method: "POST",
        credentials: "include",
        body: form,
        signal: ctrl.signal,
      });
      if (!res.ok) throw new ApiError(res.status, await res.text());
      return await res.json();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        throw new ApiError(0, "Import timed out after 60s — check the server logs.");
      }
      throw e;
    } finally {
      window.clearTimeout(timer);
    }
  },
  rebuildMen: (seed?: number) =>
    req<any>("/api/admin/men/rebuild", { method: "POST", body: JSON.stringify({ seed: seed ?? null }) }),
  rebuildWomen: (seed?: number) =>
    req<any>("/api/admin/women/rebuild", { method: "POST", body: JSON.stringify({ seed: seed ?? null }) }),
  lock: (tid: number) => req<any>(`/api/admin/tournaments/${tid}/lock`, { method: "POST" }),
  unlock: (tid: number) => req<any>(`/api/admin/tournaments/${tid}/unlock`, { method: "POST" }),

  updateScore: (matchId: number, games: Game[]) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/score`, { method: "PUT", body: JSON.stringify({ games }) }),
  retire: (matchId: number, retiredPlayerId: number) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/retire`, {
      method: "POST",
      body: JSON.stringify({ retired_player_id: retiredPlayerId }),
    }),
  unretire: (matchId: number) => req<Partial<Match>>(`/api/admin/matches/${matchId}/retire`, { method: "DELETE" }),
  resetMatch: (matchId: number) => req<Partial<Match>>(`/api/admin/matches/${matchId}/reset`, { method: "POST" }),
  /** Put a player into one side of a match, or pass null to clear it to TBD. */
  setMatchSlot: (matchId: number, slot: "a" | "b", player_id: number | null) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/slot`, {
      method: "PUT",
      body: JSON.stringify({ slot, player_id }),
    }),
  setSchedule: (matchId: number, scheduled_time: string) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/schedule`, {
      method: "PUT",
      body: JSON.stringify({ scheduled_time }),
    }),
  noShow: (matchId: number, noShowPlayerId: number) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/no-show`, {
      method: "POST",
      body: JSON.stringify({ no_show_player_id: noShowPlayerId }),
    }),
  clearNoShow: (matchId: number) =>
    req<Partial<Match>>(`/api/admin/matches/${matchId}/no-show`, { method: "DELETE" }),

  flagPlayer: (playerId: number, flagged: boolean, note?: string) =>
    req<any>(`/api/admin/players/${playerId}/flag`, {
      method: "POST",
      body: JSON.stringify({ flagged, note: note ?? null }),
    }),
  /** Cross a player off the draw (or put them back). Purely a marker: it never
   * advances anyone, which is why it applies whoever their opponent is. */
  strikePlayer: (playerId: number, struck: boolean) =>
    req<{ id: number; struck: boolean }>(`/api/admin/players/${playerId}/strike`, {
      method: "POST",
      body: JSON.stringify({ struck }),
    }),
  reportPlayer: (playerId: number, reported: boolean) =>
    req<{ id: number; reported: boolean }>(`/api/admin/players/${playerId}/report`, {
      method: "POST",
      body: JSON.stringify({ reported }),
    }),
  scheduleSpecific: (body: {
    text: string;
    day_label: string;
    start: string;
    courts: string[];
    minutes_per_match: number;
  }) => req<any>("/api/admin/schedule-specific", { method: "POST", body: JSON.stringify(body) }),
  swap: (tid: number, x: number, y: number) =>
    req<any>(`/api/admin/tournaments/${tid}/swap`, {
      method: "POST",
      body: JSON.stringify({ player_x_id: x, player_y_id: y }),
    }),
  walkin: (category: Category, body: { name: string; phone: string; experience: string; group_label: string | null }) =>
    req<any>(`/api/admin/walkin/${category}`, { method: "POST", body: JSON.stringify(body) }),

  listFormats: (tid: number) => req<RoundFormat[]>(`/api/admin/tournaments/${tid}/formats`),
  upsertFormat: (tid: number, fmt: Omit<RoundFormat, "id">) =>
    req<RoundFormat>(`/api/admin/tournaments/${tid}/formats`, { method: "PUT", body: JSON.stringify(fmt) }),
  deleteFormat: (tid: number, round: number) =>
    req<any>(`/api/admin/tournaments/${tid}/formats/${round}`, { method: "DELETE" }),

  audit: () => req<any[]>("/api/admin/audit"),
};
