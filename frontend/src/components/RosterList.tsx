import { useCallback, useEffect, useMemo, useState } from "react";
import { Category, Player, api } from "../api";
import { expTag } from "../bracket";

type Filter = "all" | Category;

export default function RosterList({ editable, onChanged }: { editable: boolean; onChanged: () => void }) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPlayers(await api.roster());
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

  async function toggleFlag(p: Player) {
    await api.flagPlayer(p.id, !p.flagged);
    load();
    onChanged();
  }

  async function toggleNoShow(p: Player) {
    await api.noShowPlayer(p.id, !p.no_show);
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
              filter === f ? "bg-court text-white border-court" : "bg-white text-slate-600 border-slate-200"
            }`}
          >
            {f === "all" ? "All" : f === "men" ? "Men" : "Women"}
            <span className="ml-1 text-[10px] opacity-70">
              {f === "all" ? players.length : players.filter((p) => p.category === f).length}
            </span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="py-12 text-center text-slate-500">
          <p className="text-lg">No entries yet.</p>
          <p className="text-sm mt-1">Import a CSV from the admin toolbar.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Phone</th>
                <th className="px-3 py-2">Group</th>
                <th className="px-3 py-2">Level</th>
                {editable && <th className="px-3 py-2">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((p) => {
                const tag = expTag(p.experience_level);
                return (
                  <tr key={p.id} className={p.no_show ? "bg-red-50/50" : undefined}>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-800">{p.full_name}</div>
                      {p.flagged && <span className="text-[10px] text-amber-600">⭐ Shortlisted</span>}
                      {p.no_show && <span className="text-[10px] text-red-600 ml-1">No show</span>}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {p.phone ? (
                        <a href={`tel:${p.phone}`} className="text-court hover:underline">
                          {p.phone}
                        </a>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                      {p.category === "men" ? p.group_label ?? "—" : "Main"}
                    </td>
                    <td className="px-3 py-2">
                      {tag ? <span className={`text-[9px] px-1 rounded ${tag.cls}`}>{tag.label}</span> : "—"}
                    </td>
                    {editable && (
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => toggleFlag(p)}
                            title="Shortlist — keep even if they lose"
                            className={`text-sm ${p.flagged ? "text-amber-500" : "text-slate-300 hover:text-amber-400"}`}
                          >
                            {p.flagged ? "★" : "☆"}
                          </button>
                          <button
                            onClick={() => toggleNoShow(p)}
                            title="Mark as no show"
                            className={`text-xs px-2 py-0.5 rounded border ${
                              p.no_show
                                ? "bg-red-100 border-red-300 text-red-700"
                                : "border-slate-200 text-slate-500 hover:border-red-200"
                            }`}
                          >
                            {p.no_show ? "No show ✓" : "No show"}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
