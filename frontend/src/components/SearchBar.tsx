import { useEffect, useRef, useState } from "react";
import { ApiError, Category, PlayerEdit, SearchMatch, SearchResult, api, currentMatch } from "../api";

interface Props {
  isAdmin: boolean;
  /** Show a player's tie in the bracket. `matchId` scrolls to and highlights that
   * exact match; without one we just switch to their group. */
  onPick: (category: Category, group: string | null, matchId?: number, playerId?: number) => void;
  onChanged: () => void;
}

export default function SearchBar({ isAdmin, onPick, onChanged }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
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

  /** Jump to a specific tie (or, with no match, just to the player's group) and
   * dismiss the dropdown so the bracket underneath is actually visible. */
  function goTo(r: SearchResult, m: SearchMatch | null) {
    onPick(r.category, r.group_label, m?.match_id, r.id);
    setOpen(false);
  }

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

  async function toggleReported(r: SearchResult) {
    const next = !r.reported;
    setResults((prev) => prev.map((x) => (x.id === r.id ? { ...x, reported: next } : x)));
    try {
      await api.reportPlayer(r.id, next);
      // Refresh the draw too: the same player carries a check on their match
      // card, and marking someone in from here has to show up there as well.
      onChanged();
    } catch {
      setResults((prev) => prev.map((x) => (x.id === r.id ? { ...x, reported: !next } : x)));
    }
  }

  /** Apply an entry correction, then refresh: the name shows on match cards too. */
  async function saveEdit(r: SearchResult, patch: PlayerEdit) {
    const updated = await api.updatePlayer(r.id, patch);
    setResults((prev) =>
      prev.map((x) =>
        x.id === r.id
          ? {
              ...x,
              full_name: updated.full_name,
              phone: updated.phone,
              registration_number: updated.registration_number,
              year_of_study: updated.year_of_study,
              experience_level: updated.experience_level,
            }
          : x,
      ),
    );
    setEditingId(null);
    onChanged();
  }

  const groupLabel = (r: SearchResult) => (r.category === "men" ? `Group ${r.group_label}` : "Women");

  return (
    <div ref={boxRef} className="relative w-full sm:max-w-md">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(e) => {
          // Enter on a single unambiguous hit goes straight to their tie.
          if (e.key === "Enter" && results.length === 1) {
            goTo(results[0], currentMatch(results[0]));
          }
          if (e.key === "Escape") setOpen(false);
        }}
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
                  onClick={() => goTo(r, currentMatch(r))}
                  title={`Show ${r.full_name} in the bracket`}
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
                    <button
                      onClick={() => toggleReported(r)}
                      title={r.reported ? "Reported — click to unmark" : "Mark as reported / checked in"}
                      className={`text-xs font-medium px-2.5 py-1 rounded-md border ${
                        r.reported
                          ? "border-emerald-300 text-emerald-700 bg-emerald-50"
                          : "border-slate-200 text-slate-500 hover:bg-slate-50"
                      }`}
                    >
                      {r.reported ? "✓ Reported" : "Report"}
                    </button>
                  )}
                  {isAdmin && (
                    <button
                      onClick={() => setEditingId((v) => (v === r.id ? null : r.id))}
                      className={`text-xs font-medium px-2.5 py-1 rounded-md border ${
                        editingId === r.id
                          ? "border-court text-white bg-court"
                          : "border-slate-200 text-slate-500 hover:bg-slate-50"
                      }`}
                    >
                      Edit
                    </button>
                  )}
                  {isAdmin && (
                    <button
                      onClick={() => remove(r)}
                      className="text-xs font-medium px-2.5 py-1 rounded-md border border-red-300 text-red-600 bg-red-50 hover:bg-red-100"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
              {isAdmin && editingId === r.id && (
                <EntryEditor
                  key={`edit-${r.id}`}
                  player={r}
                  onSave={(patch) => saveEdit(r, patch)}
                  onCancel={() => setEditingId(null)}
                />
              )}

              {/* Match info — each row jumps to that tie in the bracket. */}
              <div className="mt-1 space-y-0.5">
                {r.matches.length === 0 && <div className="text-xs text-slate-400">No draw yet.</div>}
                {r.matches.map((m) => (
                  <button
                    key={m.match_id}
                    onClick={() => goTo(r, m)}
                    title="Open this match in the bracket"
                    className="w-full text-left text-xs text-slate-500 flex items-center gap-1.5 flex-wrap rounded px-1 -mx-1 py-0.5 hover:bg-court/5 hover:text-slate-700 group"
                  >
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
                    <span className="ml-auto shrink-0 text-court opacity-0 group-hover:opacity-100 transition-opacity">
                      Show in draw →
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Inline correction form for one entry.
 *
 * Entries arrive from a Google Form filled in by hundreds of students, so the
 * data is only as good as what they typed — this is how an organiser fixes a
 * misspelt name or a wrong phone number without touching the database. Only the
 * fields that are safe to change mid-event appear: category and group decide
 * which draw someone is in, so those stay with the rebuild / move-to-group
 * tools that know how to redraw a bracket afterwards.
 */
function EntryEditor({
  player,
  onSave,
  onCancel,
}: {
  player: SearchResult;
  onSave: (patch: PlayerEdit) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(player.full_name);
  const [phone, setPhone] = useState(player.phone ?? "");
  const [reg, setReg] = useState(player.registration_number ?? "");
  const [year, setYear] = useState(player.year_of_study ?? "");
  const [exp, setExp] = useState(player.experience_level ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onSave({
        full_name: name,
        phone,
        registration_number: reg,
        year_of_study: year,
        experience_level: exp,
      });
    } catch (e) {
      const d = e instanceof ApiError ? e.detail : null;
      setError(
        d && typeof d === "object" && "message" in (d as any)
          ? String((d as any).message)
          : "Could not save that change.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2 space-y-1.5">
      <Row label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
      </Row>
      <Row label="Phone">
        <input
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          inputMode="tel"
          placeholder="10 digits; +91 and spaces are fine"
          className={INPUT}
        />
      </Row>
      <Row label="Reg no.">
        <input value={reg} onChange={(e) => setReg(e.target.value)} className={INPUT} />
      </Row>
      <Row label="Year">
        <input value={year} onChange={(e) => setYear(e.target.value)} className={INPUT} />
      </Row>
      <Row label="Level">
        <input
          value={exp}
          onChange={(e) => setExp(e.target.value)}
          placeholder="Nationals / District / School / Casual / Beginner"
          className={INPUT}
        />
      </Row>
      {error && <div className="text-[11px] text-red-600 bg-red-50 rounded px-2 py-1">{error}</div>}
      <div className="flex items-center gap-2 pt-0.5">
        <button
          onClick={submit}
          disabled={busy}
          className="text-xs bg-court text-white px-2.5 py-1 rounded disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save changes"}
        </button>
        <button onClick={onCancel} className="text-xs px-2.5 py-1 rounded border border-slate-200 text-slate-500">
          Cancel
        </button>
        <span className="text-[10px] text-slate-400">
          Level affects group balance the next time the men's draw is rebuilt.
        </span>
      </div>
    </div>
  );
}

const INPUT = "flex-1 min-w-0 rounded border border-slate-200 px-1.5 py-1 text-xs";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-[10px] uppercase tracking-wide text-slate-400">{label}</span>
      {children}
    </label>
  );
}
