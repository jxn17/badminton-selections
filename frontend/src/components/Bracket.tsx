import { useEffect, useState } from "react";
import { Bracket as BracketData, api } from "../api";
import { groupByRound, playerMap, resolveFormat, roundName, roundNameShort } from "../bracket";
import MatchCard from "./MatchCard";

interface Props {
  data: BracketData;
  editable: boolean;
  onChanged: () => void;
  highlightPlayerId?: number | null;
  onHighlightClear?: () => void;
}

export default function Bracket({ data, editable, onChanged, highlightPlayerId, onHighlightClear }: Props) {
  const rounds = groupByRound(data.matches);
  const roundNumbers = [...rounds.keys()].sort((a, b) => a - b);
  const totalRounds = roundNumbers.length;
  const players = playerMap(data.players);

  const [swapMode, setSwapMode] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [swapMsg, setSwapMsg] = useState<string | null>(null);
  const [mobileRound, setMobileRound] = useState<number>(roundNumbers[0] ?? 1);

  useEffect(() => {
    // Keep the phone round-selector valid when the bracket changes.
    if (!roundNumbers.includes(mobileRound)) setMobileRound(roundNumbers[0] ?? 1);
  }, [data.tournament.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // When a player is highlighted from search, jump the mobile round selector
  // to whichever round contains their earliest non-bye match.
  useEffect(() => {
    if (!highlightPlayerId) return;
    for (const rn of roundNumbers) {
      const match = rounds.get(rn)?.find(
        (m) => !m.is_bye && (m.player_a_id === highlightPlayerId || m.player_b_id === highlightPlayerId)
      );
      if (match) { setMobileRound(rn); break; }
    }
  }, [highlightPlayerId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onSelectForSwap(pid: number) {
    setSwapMsg(null);
    if (selected === null) return setSelected(pid);
    if (selected === pid) return setSelected(null);
    try {
      await api.swap(data.tournament.id, selected, pid);
      setSelected(null);
      onChanged();
      setSwapMsg("Swapped.");
    } catch (e: any) {
      const d = e?.detail;
      setSwapMsg(typeof d === "object" ? d.message : String(d ?? "Swap failed."));
      setSelected(null);
    }
  }

  if (data.matches.length === 0) {
    return (
      <div className="text-center py-16 text-slate-500">
        <p className="text-lg">No draw generated yet.</p>
        <p className="text-sm mt-1">{data.players.length} entries. An admin needs to build the draw.</p>
      </div>
    );
  }

  const cardProps = (m: (typeof data.matches)[number], wide: boolean) => ({
    key: m.id,
    match: m,
    players,
    format: resolveFormat(data.formats, m.round_number),
    editable,
    onChanged,
    swapMode,
    selectedForSwap: selected,
    onSelectForSwap,
    wide,
    highlightPlayerId: highlightPlayerId ?? null,
    onHighlightClear: onHighlightClear ?? (() => {}),
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
                      ? `Best of ${fmt.games_to_win_match * 2 - 1}, to ${fmt.points_to_win}${fmt.alt_points_to_win ? ` or ${fmt.alt_points_to_win}` : ""}`
                      : `1 game to ${fmt.points_to_win}${fmt.alt_points_to_win ? ` or ${fmt.alt_points_to_win}` : ""}`}
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
