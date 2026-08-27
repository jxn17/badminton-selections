import { useEffect, useState } from "react";
import { ApiError, Game, Match, Player, RoundFormat, api } from "../api";
import { expTag, maxGames } from "../bracket";

interface Props {
  match: Match;
  players: Map<number, Player>;
  format: RoundFormat;
  editable: boolean;
  onChanged: () => void;
  swapMode: boolean;
  selectedForSwap: number | null;
  onSelectForSwap: (playerId: number) => void;
  wide?: boolean; // full-width on phones
}

interface CellPair {
  a: string;
  b: string;
}

export default function MatchCard({
  match,
  players,
  format,
  editable,
  onChanged,
  swapMode,
  selectedForSwap,
  onSelectForSwap,
  wide = false,
}: Props) {
  const cols = maxGames(format);
  const [cells, setCells] = useState<CellPair[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [errorGame, setErrorGame] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [time, setTime] = useState(match.scheduled_time ?? "");
  // Local override so the star flips the instant it is clicked, before the
  // server round-trip and bracket refetch land.
  const [flagOverride, setFlagOverride] = useState<Record<number, boolean>>({});

  useEffect(() => {
    const next: CellPair[] = [];
    for (let i = 0; i < cols; i++) {
      const g = match.games.find((x) => x.game_number === i + 1);
      next.push({ a: g ? String(g.score_a) : "", b: g ? String(g.score_b) : "" });
    }
    setCells(next);
    setTime(match.scheduled_time ?? "");
  }, [match, cols]);

  const winnerId = match.winner_id;
  const retiredId = match.retired_player_id;

  async function save() {
    setSaving(true);
    setError(null);
    setErrorGame(null);
    const games: Game[] = [];
    cells.forEach((c, i) => {
      if (c.a !== "" && c.b !== "")
        games.push({ game_number: i + 1, score_a: Number(c.a), score_b: Number(c.b) });
    });
    try {
      await api.updateScore(match.id, games);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object") {
        const d = e.detail as { message?: string; game_number?: number };
        setError(d.message ?? "Invalid score.");
        setErrorGame(d.game_number ?? null);
      } else setError(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleRetire(pid: number | null) {
    if (pid === null) return;
    setError(null);
    try {
      if (retiredId === pid) await api.unretire(match.id);
      else await api.retire(match.id, pid);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    }
  }

  async function reset() {
    setError(null);
    try {
      await api.resetMatch(match.id);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "Failed to reset.");
    }
  }

  async function toggleFlag(p: Player) {
    const next = !isFlagged(p);
    setFlagOverride((prev) => ({ ...prev, [p.id]: next }));
    try {
      await api.flagPlayer(p.id, next);
      onChanged();
    } catch (e) {
      // Roll the star back if the server rejected it.
      setFlagOverride((prev) => ({ ...prev, [p.id]: !next }));
      setError(e instanceof Error ? e.message : "Failed.");
    }
  }

  function isFlagged(p: Player): boolean {
    return flagOverride[p.id] ?? p.flagged;
  }

  async function saveTime() {
    try {
      await api.setSchedule(match.id, time);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed.");
    }
  }

  function scoreCellClass(side: "a" | "b", gameNumber: number): string {
    const c = cells[gameNumber - 1];
    if (!c) return "";
    const a = Number(c.a);
    const b = Number(c.b);
    const winning = side === "a" ? a > b : b > a;
    const hl = match.status === "completed" && winning && c.a !== "" && c.b !== "";
    return hl ? "font-bold text-court" : "text-slate-500";
  }

  const PlayerRow = ({ side, id }: { side: "a" | "b"; id: number | null }) => {
    const p = id !== null ? players.get(id) ?? null : null;
    const isWinner = id !== null && id === winnerId;
    const isRetired = id !== null && id === retiredId;
    const isByeSlot = match.is_bye && id === null;
    const tag = p ? expTag(p.experience_level) : null;
    const selected = id !== null && selectedForSwap === id;

    return (
      <div
        className={`flex items-start gap-2 px-2.5 py-1.5 ${isWinner ? "font-semibold text-slate-900" : "text-slate-600"} ${
          selected ? "ring-2 ring-court rounded" : ""
        }`}
      >
        <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${isWinner ? "bg-court" : ""}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <button
              disabled={!swapMode || p === null}
              onClick={() => p && onSelectForSwap(p.id)}
              className={`min-w-0 truncate text-left ${swapMode && p ? "hover:underline cursor-pointer" : "cursor-default"}`}
              title={swapMode ? "Click to select for swap" : undefined}
            >
              {isByeSlot ? <span className="text-slate-400 italic">Bye</span> : p ? p.full_name : "TBD"}
            </button>
            {p?.is_walkin && (
              <span className="text-[9px] uppercase bg-purple-100 text-purple-700 px-1 rounded">spot</span>
            )}
            {/* Call sign, to the right of the name. */}
            {editable && p?.phone && (
              <a
                href={`tel:${p.phone}`}
                onClick={(e) => e.stopPropagation()}
                className="ml-auto shrink-0 text-court text-sm leading-none"
                title={`Call ${p.full_name}`}
              >
                📞
              </a>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {tag && <span className={`text-[9px] px-1 rounded ${tag.cls}`}>{tag.label}</span>}
            {/* Phone number only, below the name. */}
            {editable && p?.phone && (
              <a
                href={`tel:${p.phone}`}
                onClick={(e) => e.stopPropagation()}
                className="text-[10px] text-court hover:underline tabular-nums"
              >
                {p.phone}
              </a>
            )}
          </div>
        </div>
        {isRetired && (
          <span className="text-[10px] font-semibold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">RET</span>
        )}
        {match.is_bye && id === winnerId && (
          <span className="text-[10px] font-semibold text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">BYE</span>
        )}
        {editable && p && (
          <button
            onClick={() => toggleFlag(p)}
            title="Flag / shortlist"
            className={`text-lg leading-none px-0.5 ${isFlagged(p) ? "text-amber-500" : "text-slate-300 hover:text-amber-400"}`}
          >
            {isFlagged(p) ? "★" : "☆"}
          </button>
        )}
        <div className="flex gap-1">
          {cells.map((c, i) =>
            editable && !match.is_bye ? (
              <input
                key={i}
                inputMode="numeric"
                value={side === "a" ? c.a : c.b}
                onChange={(e) => {
                  const v = e.target.value.replace(/[^0-9]/g, "");
                  setCells((prev) => prev.map((pp, idx) => (idx === i ? { ...pp, [side]: v } : pp)) as CellPair[]);
                }}
                className={`w-8 text-center text-sm rounded border px-0.5 py-0.5 ${
                  errorGame === i + 1 ? "border-red-400 bg-red-50" : "border-slate-200"
                }`}
                aria-label={`game ${i + 1} score`}
              />
            ) : (
              <div key={i} className={`w-7 text-center text-sm tabular-nums ${scoreCellClass(side, i + 1)}`}>
                {side === "a" ? c.a : c.b}
              </div>
            ),
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={`bg-white rounded-lg border border-slate-200 shadow-sm ${wide ? "w-full" : "w-72"}`}>
      <PlayerRow side="a" id={match.player_a_id} />
      <div className="border-t border-slate-100" />
      <PlayerRow side="b" id={match.player_b_id} />

      {/* Schedule row */}
      {(editable || match.scheduled_time) && !match.is_bye && (
        <div className="border-t border-slate-100 px-2.5 py-1.5 flex items-center gap-2">
          <span className="text-[10px] text-slate-400">🕑</span>
          {editable ? (
            <input
              value={time}
              onChange={(e) => setTime(e.target.value)}
              onBlur={saveTime}
              placeholder="e.g. Sat 10:30, Court 2"
              className="flex-1 text-[11px] rounded border border-slate-200 px-1.5 py-0.5"
            />
          ) : (
            <span className="text-[11px] text-slate-500">{match.scheduled_time}</span>
          )}
        </div>
      )}

      {editable && !match.is_bye && (
        <div className="border-t border-slate-100 px-2 py-2 space-y-2">
          {error && <div className="text-[11px] text-red-600 bg-red-50 rounded px-2 py-1">{error}</div>}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={save}
              disabled={saving || match.player_a_id === null || match.player_b_id === null}
              className="text-xs bg-court text-white px-2 py-1 rounded disabled:opacity-40"
            >
              {saving ? "…" : "Save"}
            </button>
            <button
              onClick={() => toggleRetire(match.player_a_id)}
              disabled={match.player_a_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                retiredId === match.player_a_id ? "bg-amber-100 border-amber-300 text-amber-800" : "border-slate-200 text-slate-600"
              }`}
            >
              RET A
            </button>
            <button
              onClick={() => toggleRetire(match.player_b_id)}
              disabled={match.player_b_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                retiredId === match.player_b_id ? "bg-amber-100 border-amber-300 text-amber-800" : "border-slate-200 text-slate-600"
              }`}
            >
              RET B
            </button>
            {(match.status === "completed" || match.games.length > 0) && (
              <button onClick={reset} className="text-xs px-2 py-1 rounded border border-slate-200 text-slate-500">
                Reset
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
