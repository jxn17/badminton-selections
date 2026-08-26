import { useEffect, useRef, useState } from "react";
import { Category, SearchResult, api } from "../api";

interface Props {
  isAdmin: boolean;
  onPick: (category: Category, group: string | null) => void;
  onChanged: () => void;
}

export default function SearchBar({ isAdmin, onPick, onChanged }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Debounced search.
  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    const h = window.setTimeout(async () => {
      try {
        setResults(await api.search(q));
        setOpen(true);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(h);
  }, [q]);

  // Close on outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function remove(r: SearchResult) {
    if (!confirm(`Remove ${r.full_name}? Their opponent gets a walkover. This can't be undone.`)) return;
    try {
      await api.removePlayer(r.id);
      setResults((prev) => prev.filter((x) => x.id !== r.id));
      onChanged();
    } catch (e: any) {
      alert(typeof e?.detail === "object" ? e.detail.message : "Could not remove — they may have already played.");
    }
  }

  const groupLabel = (r: SearchResult) => (r.category === "men" ? `Group ${r.group_label}` : "Women");

  return (
    <div ref={boxRef} className="relative w-full sm:max-w-md">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        placeholder="🔍 Search a player by name…"
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      {open && q.trim().length >= 2 && (
        <div className="absolute z-30 mt-1 w-full max-h-[70vh] overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-lg">
          {loading && <div className="px-3 py-2 text-xs text-slate-400">Searching…</div>}
          {!loading && results.length === 0 && (
            <div className="px-3 py-3 text-sm text-slate-500">No players match “{q}”.</div>
          )}
          {results.map((r) => (
            <div key={r.id} className="px-3 py-2 border-b border-slate-100 last:border-0">
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => {
                    onPick(r.category, r.group_label);
                    setOpen(false);
                  }}
                  className="text-left font-medium text-slate-800 hover:text-court truncate"
                >
                  {r.full_name}
                  <span className="ml-2 text-[10px] font-normal text-white bg-court/80 px-1.5 py-0.5 rounded">
                    {groupLabel(r)}
                  </span>
                </button>
                <div className="flex items-center gap-2 shrink-0">
                  {isAdmin && r.phone && (
                    <a href={`tel:${r.phone}`} className="text-xs text-court" title={`Call ${r.full_name}`}>
                      📞
                    </a>
                  )}
                  {isAdmin && (
                    <button onClick={() => remove(r)} className="text-xs text-red-500 hover:underline">
                      Remove
                    </button>
                  )}
                </div>
              </div>
              {/* Match info */}
              <div className="mt-1 space-y-0.5">
                {r.matches.length === 0 && <div className="text-xs text-slate-400">No draw yet.</div>}
                {r.matches.map((m) => (
                  <div key={m.match_id} className="text-xs text-slate-500 flex items-center gap-1.5 flex-wrap">
                    <span className="text-slate-400">{m.round_name}:</span>
                    {m.is_bye ? (
                      <span className="italic">Bye</span>
                    ) : (
                      <span className="text-slate-700">vs {m.opponent}</span>
                    )}
                    {m.scheduled_time && <span className="text-court">🕑 {m.scheduled_time}</span>}
                    {m.result && (
                      <span className={m.result === "won" ? "text-emerald-600" : "text-slate-400"}>({m.result})</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
