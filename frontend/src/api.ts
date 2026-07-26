// Typed API client. All requests use credentials so the admin session cookie
// rides along. Read endpoints are public; /admin/* require an admin session.

export type Category = "men" | "women";

export interface Player {
  id: number;
  full_name: string;
  college_branch: string | null;
  states_nationals: string | null;
  category: Category;
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

export interface Me {
  authenticated: boolean;
  email: string | null;
  is_admin: boolean;
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

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export const api = {
  me: () => req<Me>("/api/auth/me"),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  devLogin: () => req<{ ok: boolean; email: string }>("/api/auth/dev-login", { method: "POST" }),

  bracket: (cat: Category) => req<Bracket>(`/api/categories/${cat}/bracket`),

  // Admin
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
  generateDraw: (cat: Category, seed?: number) =>
    req<{ seed: number; bracket_size: number; num_byes: number }>(
      `/api/admin/${cat}/draw`,
      { method: "POST", body: JSON.stringify({ seed: seed ?? null }) },
    ),
  lockDraw: (cat: Category) =>
    req<{ status: string }>(`/api/admin/${cat}/lock`, { method: "POST" }),

  updateScore: (cat: Category, matchId: number, games: Game[]) =>
    req<Match>(`/api/admin/${cat}/matches/${matchId}/score`, {
      method: "PUT",
      body: JSON.stringify({ games }),
    }),
  retire: (cat: Category, matchId: number, retiredPlayerId: number) =>
    req<Match>(`/api/admin/${cat}/matches/${matchId}/retire`, {
      method: "POST",
      body: JSON.stringify({ retired_player_id: retiredPlayerId }),
    }),
  unretire: (cat: Category, matchId: number) =>
    req<Match>(`/api/admin/${cat}/matches/${matchId}/retire`, { method: "DELETE" }),
  resetMatch: (cat: Category, matchId: number) =>
    req<Match>(`/api/admin/${cat}/matches/${matchId}/reset`, { method: "POST" }),

  listFormats: (cat: Category) => req<RoundFormat[]>(`/api/admin/${cat}/formats`),
  upsertFormat: (cat: Category, fmt: Omit<RoundFormat, "id">) =>
    req<RoundFormat>(`/api/admin/${cat}/formats`, {
      method: "PUT",
      body: JSON.stringify(fmt),
    }),
  deleteFormat: (cat: Category, roundNumber: number) =>
    req<{ ok: boolean }>(`/api/admin/${cat}/formats/${roundNumber}`, { method: "DELETE" }),

  listAdmins: () => req<{ id: number; email: string; added_by: string | null }[]>("/api/admin/admins"),
  addAdmin: (email: string) =>
    req<{ id: number; email: string }>("/api/admin/admins", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  removeAdmin: (id: number) =>
    req<{ ok: boolean }>(`/api/admin/admins/${id}`, { method: "DELETE" }),
};
