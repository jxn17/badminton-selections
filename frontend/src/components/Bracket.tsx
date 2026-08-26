import { useState } from "react";
import { Bracket as BracketData, api } from "../api";
import { groupByRound, playerMap, resolveFormat, roundName } from "../bracket";
import MatchCard from "./MatchCard";

interface Props {
  data: BracketData;
  editable: boolean;
  onChanged: () => void;
}

export default function Bracket({ data, editable, onChanged }: Props) {
  const rounds = groupByRound(data.matches);
  const roundNumbers = [...rounds.keys()].sort((a, b) => a - b);
  const totalRounds = roundNumbers.length;
  const players = playerMap(data.players);

  const [swapMode, setSwapMode] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [swapMsg, setSwapMsg] = useState<string | null>(null);

  async function onSelectForSwap(pid: number) {
    setSwapMsg(null);
    if (selected === null) {
      setSelected(pid);
      return;
    }
    if (selected === pid) {
      setSelected(null);
      return;
    }
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

  return (
    <div>
      {editable && (
        <div className="mb-3 flex items-center gap-2 text-sm">
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
                ? "Click a player, then click who to swap them with."
                : `Selected ${players.get(selected)?.full_name ?? ""} — now click the other player.`}
            </span>
          )}
          {swapMsg && <span className="text-xs text-slate-500">{swapMsg}</span>}
        </div>
      )}

      <div className="overflow-x-auto pb-4">
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
                    <MatchCard
                      key={m.id}
                      match={m}
                      players={players}
                      format={fmt}
                      editable={editable}
                      onChanged={onChanged}
                      swapMode={swapMode}
                      selectedForSwap={selected}
                      onSelectForSwap={onSelectForSwap}
                    />
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
