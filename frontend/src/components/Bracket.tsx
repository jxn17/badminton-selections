import { Bracket as BracketData, Category } from "../api";
import { groupByRound, playerMap, resolveFormat, roundName } from "../bracket";
import MatchCard from "./MatchCard";

interface Props {
  data: BracketData;
  category: Category;
  editable: boolean;
  onChanged: () => void;
}

export default function Bracket({ data, category, editable, onChanged }: Props) {
  const rounds = groupByRound(data.matches);
  const roundNumbers = [...rounds.keys()].sort((a, b) => a - b);
  const totalRounds = roundNumbers.length;
  const players = playerMap(data.players);

  if (data.matches.length === 0) {
    return (
      <div className="text-center py-16 text-slate-500">
        <p className="text-lg">No draw yet for the {category === "men" ? "men's" : "women's"} bracket.</p>
        <p className="text-sm mt-1">
          {data.players.length} {data.players.length === 1 ? "entry" : "entries"} registered.
          An admin needs to generate the draw.
        </p>
      </div>
    );
  }

  return (
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
                    category={category}
                    editable={editable}
                    onChanged={onChanged}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
