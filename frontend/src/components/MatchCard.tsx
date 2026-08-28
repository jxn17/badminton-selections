import { useEffect, useRef, useState } from "react";
import { ApiError, Game, Match, Player, RoundFormat, api } from "../api";
import { expTag, maxGames } from "../bracket";

interface Props {
  match: Match;
  players: Map<number, Player>;
  format: RoundFormat;
  editable: boolean;
  // Per-match actions (score/RET/no-show/reset/schedule) patch the bracket
  // locally from their own response — no full refetch, so the result shows up
  // as fast as the network round-trip for that one small request.
  onMatchUpdated: (updated: Partial<Match> & { id: number }) => void;
  // Flag/report only need to eventually update counts shown elsewhere (the
  // shortlist badge); the star/check itself flips instantly via local state.
  onCountsChanged: () => void;
  swapMode: boolean;
  selectedForSwap: number | null;
  onSelectForSwap: (playerId: number) => void;
  wide?: boolean; // full-width on phones
  // Set when the player search asked for this tie: the card scrolls itself into
  // view and rings until the highlight is cleared.
  highlight?: boolean;
  highlightPlayerId?: number | null;
}

interface CellPair {
  a: string;
  b: string;
}

function errText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const d = e.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in (d as any)) return (d as any).message;
  }
  return e instanceof Error ? e.message : fallback;
}

export default function MatchCard({
  match,
  players,
  format,
  editable,
  onMatchUpdated,
  onCountsChanged,
  swapMode,
  selectedForSwap,
  onSelectForSwap,
  wide = false,
  highlight = false,
  highlightPlayerId = null,
}: Props) {
  const cols = maxGames(format);
  const cardRef = useRef<HTMLDivElement>(null);
  const [cells, setCells] = useState<CellPair[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [errorGame, setErrorGame] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [time, setTime] = useState(match.scheduled_time ?? "");
  // Local overrides so the star/check flip instantly, before the network round
  // trip lands — these are per-player UI signals, not match state.
  const [flagOverride, setFlagOverride] = useState<Record<number, boolean>>({});
  const [reportedOverride, setReportedOverride] = useState<Record<number, boolean>>({});

  // True while this admin has unsaved edits in the score boxes. The bracket
  // refetches every 15s; without this guard that refetch would wipe whatever is
  // half-typed.
  const dirtyRef = useRef(false);

  // Bring a searched-for tie onto the screen. Both the phone and the desktop
  // layouts render every card, but the copy that isn't in play is display:none,
  // where scrollIntoView is a no-op — so only the visible one actually moves,
  // and it moves whichever container is scrollable (the page on phones, the
  // horizontal round strip on desktop).
  useEffect(() => {
    if (!highlight) return;
    const el = cardRef.current;
    if (!el) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const into = (behavior: ScrollBehavior) =>
      el.scrollIntoView({ behavior, block: "center", inline: "center" });

    into(reduced ? "auto" : "smooth");
    if (reduced) return;
    // A smooth scroll only advances while the page is producing frames — in a
    // background tab, or anywhere animations are suppressed, it silently never
    // arrives. Check, and snap if it didn't: landing on the tie matters more
    // than gliding there.
    const h = window.setTimeout(() => {
      const r = el.getBoundingClientRect();
      const onScreen = r.top >= 0 && r.bottom <= window.innerHeight;
      if (!onScreen && el.offsetParent !== null) into("auto");
    }, 700);
    return () => window.clearTimeout(h);
  }, [highlight]);

  useEffect(() => {
    if (dirtyRef.current) return; // keep the admin's in-progress input
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
  const noShowId = match.no_show_player_id;

  function patch(server: Partial<Match>) {
    onMatchUpdated({ ...match, ...server, id: match.id });
  }

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
      const updated = await api.updateScore(match.id, games);
      dirtyRef.current = false; // server now matches what's on screen
      patch(updated);
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === "object") {
        const d = e.detail as { message?: string; game_number?: number };
        setError(d.message ?? "Invalid score.");
        setErrorGame(d.game_number ?? null);
      } else setError(errText(e, "Failed to save."));
    } finally {
      setSaving(false);
    }
  }

  async function toggleRetire(pid: number | null) {
    if (pid === null) return;
    setError(null);
    try {
      const updated = retiredId === pid ? await api.unretire(match.id) : await api.retire(match.id, pid);
      patch(updated);
    } catch (e) {
      setError(errText(e, "Failed."));
    }
  }

  async function toggleNoShow(pid: number | null) {
    if (pid === null) return;
    setError(null);
    try {
      const updated = noShowId === pid ? await api.clearNoShow(match.id) : await api.noShow(match.id, pid);
      patch(updated);
    } catch (e) {
      setError(errText(e, "Failed."));
    }
  }

  async function reset() {
    setError(null);
    try {
      const updated = await api.resetMatch(match.id);
      patch(updated);
    } catch (e) {
      setError(errText(e, "Failed to reset."));
    }
  }

  async function toggleFlag(p: Player) {
    const next = !isFlagged(p);
    setFlagOverride((prev) => ({ ...prev, [p.id]: next }));
    try {
      await api.flagPlayer(p.id, next);
      onCountsChanged();
    } catch (e) {
      // Roll the star back if the server rejected it.
      setFlagOverride((prev) => ({ ...prev, [p.id]: !next }));
      setError(errText(e, "Failed."));
    }
  }

  async function toggleReported(p: Player) {
    const next = !isReported(p);
    setReportedOverride((prev) => ({ ...prev, [p.id]: next }));
    try {
      await api.reportPlayer(p.id, next);
      onCountsChanged();
    } catch (e) {
      setReportedOverride((prev) => ({ ...prev, [p.id]: !next }));
      setError(errText(e, "Failed."));
    }
  }

  function isFlagged(p: Player): boolean {
    return flagOverride[p.id] ?? p.flagged;
  }
  function isReported(p: Player): boolean {
    return reportedOverride[p.id] ?? p.reported;
  }

  async function saveTime() {
    try {
      const updated = await api.setSchedule(match.id, time);
      patch(updated);
    } catch (e) {
      setError(errText(e, "Failed."));
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

  const playerRow = (side: "a" | "b", id: number | null) => {
    const p = id !== null ? players.get(id) ?? null : null;
    const isSearched = highlight && id !== null && id === highlightPlayerId;
    const isWinner = id !== null && id === winnerId;
    const isRetired = id !== null && id === retiredId;
    const isNoShow = id !== null && id === noShowId;
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
              <span className={isSearched ? "bg-amber-200/70 rounded px-1 -mx-1" : undefined}>
                {isByeSlot ? <span className="text-slate-400 italic">Bye</span> : p ? p.full_name : "TBD"}
              </span>
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
        {isNoShow && (
          <span className="text-[10px] font-semibold text-red-700 bg-red-100 px-1.5 py-0.5 rounded">NO SHOW</span>
        )}
        {match.is_bye && id === winnerId && (
          <span className="text-[10px] font-semibold text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">BYE</span>
        )}
        {editable && p && (
          <button
            onClick={() => toggleReported(p)}
            title={isReported(p) ? "Reported — click to unmark" : "Mark as reported / checked in"}
            className={`text-sm leading-none px-0.5 ${isReported(p) ? "text-emerald-600" : "text-slate-300 hover:text-emerald-500"}`}
          >
            ✓
          </button>
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
                  const v = e.target.value.replace(/[^0-9]/g, "").slice(0, 3);
                  dirtyRef.current = true;
                  setCells((prev) => prev.map((pp, idx) => (idx === i ? { ...pp, [side]: v } : pp)) as CellPair[]);
                }}
                onFocus={(e) => e.currentTarget.select()}
                onBlur={() => {
                  // Commit to the DB once the full score for this game is in,
                  // rather than on every digit.
                  const c = cells[i];
                  if (dirtyRef.current && c && c.a !== "" && c.b !== "") save();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
                className={`w-10 text-center text-sm rounded border px-1 py-0.5 ${
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
    <div
      ref={cardRef}
      className={`bg-white rounded-lg border shadow-sm transition-shadow scroll-mt-40 ${
        wide ? "w-full" : "w-72"
      } ${highlight ? "border-court ring-2 ring-court/60 shadow-md" : "border-slate-200"}`}
    >
      {playerRow("a", match.player_a_id)}
      <div className="border-t border-slate-100" />
      {playerRow("b", match.player_b_id)}

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
            <button
              onClick={() => toggleNoShow(match.player_a_id)}
              disabled={match.player_a_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                noShowId === match.player_a_id ? "bg-red-100 border-red-300 text-red-800" : "border-slate-200 text-slate-600"
              }`}
            >
              No-show A
            </button>
            <button
              onClick={() => toggleNoShow(match.player_b_id)}
              disabled={match.player_b_id === null}
              className={`text-xs px-2 py-1 rounded border ${
                noShowId === match.player_b_id ? "bg-red-100 border-red-300 text-red-800" : "border-slate-200 text-slate-600"
              }`}
            >
              No-show B
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
