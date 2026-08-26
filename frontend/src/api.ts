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
  bracket: (category: Category, group?: string | null) => {
    const q = new URLSearchParams({ category });
    if (group) q.set("group", group);
    return req<Bracket>(`/api/bracket?${q.toString()}`);
  },

  importCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/admin/import", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return res.json();
  },
  rebuildMen: (seed?: number) =>
    req<any>("/api/admin/men/rebuild", { method: "POST", body: JSON.stringify({ seed: seed ?? null }) }),
  rebuildWomen: (seed?: number) =>
    req<any>("/api/admin/women/rebuild", { method: "POST", body: JSON.stringify({ seed: seed ?? null }) }),
  lock: (tid: number) => req<any>(`/api/admin/tournaments/${tid}/lock`, { method: "POST" }),
  unlock: (tid: number) => req<any>(`/api/admin/tournaments/${tid}/unlock`, { method: "POST" }),

  updateScore: (matchId: number, games: Game[]) =>
    req<Match>(`/api/admin/matches/${matchId}/score`, { method: "PUT", body: JSON.stringify({ games }) }),
  retire: (matchId: number, retiredPlayerId: number) =>
    req<Match>(`/api/admin/matches/${matchId}/retire`, {
      method: "POST",
      body: JSON.stringify({ retired_player_id: retiredPlayerId }),
    }),
  unretire: (matchId: number) => req<Match>(`/api/admin/matches/${matchId}/retire`, { method: "DELETE" }),
  resetMatch: (matchId: number) => req<Match>(`/api/admin/matches/${matchId}/reset`, { method: "POST" }),
  setSchedule: (matchId: number, scheduled_time: string) =>
    req<any>(`/api/admin/matches/${matchId}/schedule`, {
      method: "PUT",
      body: JSON.stringify({ scheduled_time }),
    }),

  flagPlayer: (playerId: number, flagged: boolean, note?: string) =>
    req<any>(`/api/admin/players/${playerId}/flag`, {
      method: "POST",
      body: JSON.stringify({ flagged, note: note ?? null }),
    }),
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
