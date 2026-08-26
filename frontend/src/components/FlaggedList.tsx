import { useCallback, useEffect, useState } from "react";
import { Player, api } from "../api";
import { expTag } from "../bracket";

export default function FlaggedList({ editable, onChanged }: { editable: boolean; onChanged: () => void }) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);

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

  async function unflag(p: Player) {
    await api.flagPlayer(p.id, false);
    load();
    onChanged();
  }

  if (loading) return <div className="py-10 text-center text-slate-400">Loading…</div>;
  if (players.length === 0)
    return (
      <div className="py-12 text-center text-slate-500">
        <p className="text-lg">No shortlisted players yet.</p>
        <p className="text-sm mt-1">Tap ⭐ / ☆ on any player in a bracket to add them here.</p>
      </div>
    );

  const men = players.filter((p) => p.category === "men");
  const women = players.filter((p) => p.category === "women");

  const Group = ({ title, list }: { title: string; list: Player[] }) =>
    list.length === 0 ? null : (
      <div className="mb-5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
          {title} ({list.length})
        </h3>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((p) => {
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
      </div>
    );

  return (
    <div>
      <Group title="Men" list={men} />
      <Group title="Women" list={women} />
    </div>
  );
}
