import { useEffect, useState } from "react";
import { ApiError, Category, Game, Match, Player, RoundFormat, api } from "../api";
import { maxGames } from "../bracket";

interface Props {
  match: Match;
  players: Map<number, Player>;
  format: RoundFormat;
  category: Category;
  editable: boolean;
  onChanged: () => void;
}

interface CellPair {
  a: string;
  b: string;
}

function nameOf(players: Map<number, Player>, id: number | null): string {
  if (id === null) return "TBD";
  return players.get(id)?.full_name ?? `#${id}`;
}

function branchOf(players: Map<number, Player>, id: number | null): string | null {
  if (id === null) return null;
  return players.get(id)?.college_branch ?? null;
}

export default function MatchCard({
  match,
  players,
  format,
  category,
  editable,
  onChanged,
}: Props) {
  const cols = maxGames(format);
  const [cells, setCells] = useState<CellPair[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [errorGame, setErrorGame] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next: CellPair[] = [];
    for (let i = 0; i < cols; i++) {
      const g = match.games.find((x) => x.game_number === i + 1);
      next.push({ a: g ? String(g.score_a) : "", b: g ? String(g.score_b) : "" });
    }
    setCells(next);
  }, [match, cols]);

  const winnerId = match.winner_id;
  const retiredId = match.retired_player_id;

  function rowClasses(id: number | null): string {
    const base = "flex items-center gap-2 px-3 py-2";
    if (id !== null && id === winnerId) return base + " font-semibold text-slate-900";
    return base + " text-slate-600";
  }

  function scoreCellClass(side: "a" | "b", gameNumber: number): string {
    const cell = cells[gameNumber - 1];
    if (!cell) return "";
    const a = Number(cell.a);
    const b = Number(cell.b);
    const isWinningSide = side === "a" ? a > b : b > a;
    const highlight = match.status === "completed" && isWinningSide && cell.a !== "" && cell.b !== "";
    return highlight ? "font-bold text-court" : "text-slate-500";
  }

  async function save() {
    setSaving(true);
    setError(null);
    setErrorGame(null);
    const games: Game[] = [];
    cells.forEach((c, i) => {
      if (c.a !== "" && c.b !== "") {
        games.push({ game_number: i + 1, score_a: Number(c.a), score_b: Number(c.b) });
      }
    });
    try {
      await api.updateScore(category, match.id, games);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object") {
        const d = e.detail as { message?: string; game_number?: number };
        setError(d.message ?? "Invalid score.");
        setErrorGame(d.game_number ?? null);
      } else {
        setError(e instanceof Error ? e.message : "Failed to save.");
      }
    } finally {
      setSaving(false);
    }
  }

  async function toggleRetire(playerId: number | null) {
    if (playerId === null) return;
    setError(null);
    try {
      if (retiredId === playerId) await api.unretire(category, match.id);
      else await api.retire(category, match.id, playerId);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    }
  }

  async function reset() {
    setError(null);
    try {
      await api.resetMatch(category, match.id);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError) setError(String(e.detail));
      else setError("Failed to reset.");
    }
  }

  const PlayerRow = ({ side, id }: { side: "a" | "b"; id: number | null }) => {
    const branch = branchOf(players, id);
    const isWinner = id !== null && id === winnerId;
    const isRetired = id !== null && id === retiredId;
    const isByeSlot = match.is_bye && id === null;
    return (
      <div className={rowClasses(id)}>
        {isWinner && <span className="w-2 h-2 rounded-full bg-court shrink-0" title="Winner" />}
        {!isWinner && <span className="w-2 h-2 shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="truncate">
            {isByeSlot ? <span className="text-slate-400 italic">Bye</span> : nameOf(players, id)}
          </div>
          {branch && <div className="text-[11px] text-slate-400 truncate">{branch}</div>}
        </div>
        {isRetired && (
          <span className="text-[10px] font-semibold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
            RET
          </span>
        )}
        {match.is_bye && id === winnerId && (
          <span className="text-[10px] font-semibold text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
            BYE
          </span>
        )}

        {/* Score columns */}
        <div className="flex gap-1">
          {cells.map((c, i) =>
            editable && !match.is_bye ? (
              <input
                key={i}
                inputMode="numeric"
                value={side === "a" ? c.a : c.b}
                onChange={(e) => {
                  const v = e.target.value.replace(/[^0-9]/g, "");
                  setCells((prev) =>
                    prev.map((p, idx) =>
                      idx === i ? { ...p, [side]: v } : p,
                    ) as CellPair[],
                  );
                }}
                className={`w-9 text-center text-sm rounded border px-1 py-0.5 ${
                  errorGame === i + 1 ? "border-red-400 bg-red-50" : "border-slate-200"
                }`}
                aria-label={`game ${i + 1} score`}
              />
            ) : (
              <div
                key={i}
                className={`w-7 text-center text-sm tabular-nums ${scoreCellClass(side, i + 1)}`}
              >
                {side === "a" ? c.a : c.b}
              </div>
            ),
          )}
        </div>
      </div>
    );
  };

  return (
    <div
      className={`bg-white rounded-lg border shadow-sm w-64 ${
        match.status === "completed" ? "border-slate-200" : "border-slate-200"
      }`}
    >
      <PlayerRow side="a" id={match.player_a_id} />
      <div className="border-t border-slate-100" />
      <PlayerRow side="b" id={match.player_b_id} />

      {editable && !match.is_bye && (
        <div className="border-t border-slate-100 px-2 py-2 space-y-2">
          {error && (
            <div className="text-[11px] text-red-600 bg-red-50 rounded px-2 py-1">{error}</div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={save}
              disabled={saving || match.player_a_id === null || match.player_b_id === null}
              className="text-xs bg-court text-white px-2 py-1 rounded disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => toggleRetire(match.player_a_id)}
              disabled={match.player_a_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                retiredId === match.player_a_id
                  ? "bg-amber-100 border-amber-300 text-amber-800"
                  : "border-slate-200 text-slate-600"
              }`}
            >
              RET A
            </button>
            <button
              onClick={() => toggleRetire(match.player_b_id)}
              disabled={match.player_b_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                retiredId === match.player_b_id
                  ? "bg-amber-100 border-amber-300 text-amber-800"
                  : "border-slate-200 text-slate-600"
              }`}
            >
              RET B
            </button>
            {(match.status === "completed" || match.games.length > 0) && (
              <button
                onClick={reset}
                className="text-xs px-2 py-1 rounded border border-slate-200 text-slate-500"
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
