import { useCallback, useEffect, useMemo, useState } from "react";
import { Category, Player, api } from "../api";
import { expTag } from "../bracket";

type Filter = "all" | Category;

export default function FlaggedList({ editable, onChanged }: { editable: boolean; onChanged: () => void }) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPlayers(await api.flagged());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (filter === "all") return players;
    return players.filter((p) => p.category === filter);
  }, [players, filter]);

  async function unflag(p: Player) {
    await api.flagPlayer(p.id, false);
    load();
    onChanged();
  }

  if (loading) return <div className="py-10 text-center text-slate-400">Loading…</div>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {(["all", "men", "women"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-sm rounded-md border ${
              filter === f ? "bg-amber-400 text-white border-amber-400" : "bg-white text-slate-600 border-slate-200"
            }`}
          >
            {f === "all" ? "All" : f === "men" ? "Men" : "Women"}
            <span className="ml-1 text-[10px] opacity-80">
              {f === "all" ? players.length : players.filter((p) => p.category === f).length}
            </span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="py-12 text-center text-slate-500">
          <p className="text-lg">No shortlisted players yet.</p>
          <p className="text-sm mt-1">
            Tap ⭐ on any player in a bracket or the roster — even if they lose — to add them here.
          </p>
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((p) => {
            const tag = expTag(p.experience_level);
            return (
              <div key={p.id} className="bg-white border border-slate-200 rounded-lg p-3 flex items-start gap-2">
                <span>⭐</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-slate-800 truncate">
                    {p.full_name}
                    {p.group_label && <span className="text-slate-400 font-normal"> · {p.group_label}</span>}
                  </div>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {tag && <span className={`text-[9px] px-1 rounded ${tag.cls}`}>{tag.label}</span>}
                    {p.phone && (
                      <a href={`tel:${p.phone}`} className="text-xs text-court hover:underline inline-flex items-center gap-0.5">
                        📞 {p.phone}
                      </a>
                    )}
                    {p.no_show && (
                      <span className="text-[10px] text-red-600 bg-red-50 px-1 rounded">No show</span>
                    )}
                  </div>
                  {p.flag_note && <div className="text-xs text-slate-400 mt-1">{p.flag_note}</div>}
                </div>
                {editable && (
                  <button onClick={() => unflag(p)} className="text-xs text-slate-400 hover:text-red-500" title="Remove from shortlist">
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
