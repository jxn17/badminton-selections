import { useEffect, useRef, useState } from "react";
import { BracketFocus, Bracket as BracketData, Match, api } from "../api";
import { groupByRound, playerMap, resolveFormat, roundName, roundNameShort } from "../bracket";
import MatchCard from "./MatchCard";

interface Props {
  data: BracketData;
  editable: boolean;
  onChanged: () => void;
  onCountsChanged?: () => void;
  /** A tie to reveal (set by the player search). */
  focus?: BracketFocus | null;
}

export default function Bracket({ data, editable, onChanged, onCountsChanged, focus }: Props) {
  // Matches live in local state so a single score/RET/no-show/schedule edit can
  // be reflected instantly from that action's own response, instead of waiting
  // on a full bracket refetch (the old flow: PUT score -> GET whole bracket ->
  // re-render). Re-synced whenever the parent hands us fresh data (initial
  // load, group switch, the 15s poll, or a bulk admin action like a rebuild).
  const [matches, setMatches] = useState<Match[]>(data.matches);
  useEffect(() => {
    setMatches(data.matches);
  }, [data.matches]);

  const rounds = groupByRound(matches);
  const roundNumbers = [...rounds.keys()].sort((a, b) => a - b);
  const totalRounds = roundNumbers.length;
  const players = playerMap(data.players);

  const [swapMode, setSwapMode] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [swapMsg, setSwapMsg] = useState<string | null>(null);
  const [mobileRound, setMobileRound] = useState<number>(roundNumbers[0] ?? 1);
  // The match the search asked us to reveal, once it is actually in `matches`.
  const [highlighted, setHighlighted] = useState<BracketFocus | null>(null);
  // Nonce of the last pick we acted on. `matches` changes on every poll and
  // every score save, and without this the effect below would re-scroll the
  // user back to a tie they searched for minutes ago, mid-edit.
  const consumedFocus = useRef<number | null>(null);

  useEffect(() => {
    // Keep the phone round-selector valid when the bracket changes.
    if (!roundNumbers.includes(mobileRound)) setMobileRound(roundNumbers[0] ?? 1);
  }, [data.tournament.id]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Reveal a searched-for tie, exactly once per pick.
   *
   * This has to watch `matches` as well as the focus: picking a player in
   * another group swaps the whole bracket out, so the tie only exists to
   * scroll to once that group's data has landed. But `matches` also changes on
   * every 15s poll and every score save, so the nonce guard is what stops those
   * from dragging the user back here later. On phones one round is on screen at
   * a time, so switch to the tie's round first or there is nothing to reveal. */
  useEffect(() => {
    if (!focus || focus.nonce === consumedFocus.current) return;
    const target = matches.find((m) => m.id === focus.matchId);
    if (!target) return; // wrong group still on screen; wait for the next load
    consumedFocus.current = focus.nonce;
    setMobileRound(target.round_number);
    setHighlighted(focus);
    // Let the ring fade once it has done its job, so it doesn't linger as
    // permanent chrome on a card the admin is now editing. Long enough to still
    // be showing after the scroll (which may take ~1s) settles.
    const h = window.setTimeout(() => setHighlighted(null), 7000);
    return () => window.clearTimeout(h);
  }, [focus, matches]);

  /** Apply a single match's update locally: patch it in place, and if it now
   * has a winner, push that winner into the downstream match's slot right
   * away (mirroring the server's own advancement) so the next round shows the
   * result immediately instead of waiting on a refetch. Only ever called with
   * a response the server already validated, so this can't desync the bracket
   * — it's just rendering the outcome sooner. */
  function patchMatch(partial: Partial<Match> & { id: number }) {
    setMatches((prev) => {
      const prevMatch = prev.find((m) => m.id === partial.id);
      const updated: Match = prevMatch ? { ...prevMatch, ...partial } : (partial as Match);
      let next = prev.map((m) => (m.id === updated.id ? updated : m));

      if (updated.next_match_id != null) {
        const isA = updated.position_in_round % 2 === 0;
        next = next.map((m) => {
          if (m.id !== updated.next_match_id) return m;
          if (updated.winner_id != null) {
            return isA ? { ...m, player_a_id: updated.winner_id } : { ...m, player_b_id: updated.winner_id };
          }
          // Winner was cleared (reset/re-edit). Only retract if this slot still
          // holds what THIS match had previously pushed there, so we never
          // clobber a different, concurrent edit to the downstream match.
          if (prevMatch?.winner_id != null) {
            const cur = isA ? m.player_a_id : m.player_b_id;
            if (cur === prevMatch.winner_id) {
              return isA ? { ...m, player_a_id: null } : { ...m, player_b_id: null };
            }
          }
          return m;
        });
      }
      return next;
    });
  }

  /** Lightweight refresh for things that only affect counts elsewhere (e.g. the
   * shortlist badge), without paying for a full bracket refetch on every click. */
  function handleCountsChanged() {
    (onCountsChanged ?? onChanged)();
  }

  async function onSelectForSwap(pid: number) {
    setSwapMsg(null);
    if (selected === null) return setSelected(pid);
    if (selected === pid) return setSelected(null);
    try {
      await api.swap(data.tournament.id, selected, pid);
      setSelected(null);
      onChanged(); // swap restructures two matches' rosters; a full refetch is correct here
      setSwapMsg("Swapped.");
    } catch (e: any) {
      const d = e?.detail;
      setSwapMsg(typeof d === "object" ? d.message : String(d ?? "Swap failed."));
      setSelected(null);
    }
  }

  if (matches.length === 0) {
    return (
      <div className="text-center py-16 text-slate-500">
        <p className="text-lg">No draw generated yet.</p>
        <p className="text-sm mt-1">{data.players.length} entries. An admin needs to build the draw.</p>
      </div>
    );
  }

  const cardProps = (m: Match, wide: boolean) => ({
    key: m.id,
    match: m,
    highlight: highlighted?.matchId === m.id,
    highlightPlayerId: highlighted?.matchId === m.id ? highlighted.playerId : null,
    players,
    format: resolveFormat(data.formats, m.round_number),
    editable,
    onMatchUpdated: patchMatch,
    onCountsChanged: handleCountsChanged,
    swapMode,
    selectedForSwap: selected,
    onSelectForSwap,
    wide,
  });

  return (
    <div>
      {editable && (
        <div className="mb-3 flex items-center gap-2 text-sm flex-wrap">
          <button
            onClick={() => {
              setSwapMode((v) => !v);
              setSelected(null);
              setSwapMsg(null);
            }}
            className={`px-3 py-1 rounded border ${swapMode ? "bg-court text-white border-court" : "border-slate-300 text-slate-600"}`}
          >
            {swapMode ? "Swap mode: ON" : "Swap players"}
          </button>
          {swapMode && (
            <span className="text-xs text-slate-500">
              {selected === null
                ? "Tap a player, then tap who to swap them with."
                : `Selected ${players.get(selected)?.full_name ?? ""} — now tap the other player.`}
            </span>
          )}
          {swapMsg && <span className="text-xs text-slate-500">{swapMsg}</span>}
        </div>
      )}

      {/* Phone view: pick a round, see its matches stacked full-width. */}
      <div className="md:hidden">
        <div className="flex gap-1.5 overflow-x-auto pb-2 -mx-1 px-1">
          {roundNumbers.map((rn) => (
            <button
              key={rn}
              onClick={() => setMobileRound(rn)}
              className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium border ${
                mobileRound === rn ? "bg-court text-white border-court" : "bg-white text-slate-600 border-slate-200"
              }`}
            >
              {roundNameShort(rn, totalRounds)}
            </button>
          ))}
        </div>
        <div className="text-xs text-slate-400 mb-2">
          {roundName(mobileRound, totalRounds)} · {rounds.get(mobileRound)?.length ?? 0} matches
        </div>
        <div className="space-y-3">
          {rounds.get(mobileRound)!.map((m) => (
            <MatchCard {...cardProps(m, true)} />
          ))}
        </div>
      </div>

      {/* Desktop / tablet view: full horizontal bracket. */}
      <div className="hidden md:block overflow-x-auto pb-4">
        <div className="flex gap-8 min-w-max">
          {roundNumbers.map((rn) => {
            const fmt = resolveFormat(data.formats, rn);
            return (
              <div key={rn} className="flex flex-col">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-3">
                  {roundName(rn, totalRounds)}
                  <span className="ml-2 font-normal normal-case text-slate-400">
                    {fmt.games_to_win_match > 1
                      ? `Best of ${fmt.games_to_win_match * 2 - 1}, to ${fmt.points_to_win}`
                      : `1 game to ${fmt.points_to_win}`}
                  </span>
                </div>
                <div className="flex flex-col justify-around gap-4 h-full">
                  {rounds.get(rn)!.map((m) => (
                    <MatchCard {...cardProps(m, false)} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
