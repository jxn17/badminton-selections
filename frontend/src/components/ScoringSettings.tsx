import { useCallback, useEffect, useState } from "react";
import { RoundFormat, api } from "../api";

const EMPTY: Omit<RoundFormat, "id"> = {
  round_number: null,
  points_to_win: 21,
  alt_points_to_win: 11,
  win_by_two: true,
  hard_cap: 30,
  games_to_win_match: 1,
};

export default function ScoringSettings({ tournamentId }: { tournamentId: number }) {
  const [formats, setFormats] = useState<RoundFormat[]>([]);
  const [draft, setDraft] = useState<Omit<RoundFormat, "id">>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setFormats(await api.listFormats(tournamentId));
    } catch (e: any) {
      setMsg(e?.message ?? "Failed.");
    }
  }, [tournamentId]);

  useEffect(() => {
    load();
    setDraft(EMPTY);
  }, [load]);

  async function save() {
    setMsg(null);
    try {
      await api.upsertFormat(tournamentId, draft);
      setMsg("Saved.");
      setDraft(EMPTY);
      load();
    } catch (e: any) {
      setMsg(typeof e?.detail === "string" ? e.detail : "Failed to save.");
    }
  }

  async function del(round: number) {
    await api.deleteFormat(tournamentId, round);
    load();
  }

  return (
    <div className="border-t border-slate-100 pt-3 space-y-3">
      <p className="text-xs text-slate-500">
        Default (Round = all) applies everywhere; add a row with a round number to override just that round. This
        applies to the currently-selected group.
      </p>
      <div className="overflow-x-auto">
        <table className="text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pr-4">Round</th>
              <th className="py-1 pr-4">Points</th>
              <th className="py-1 pr-4">Alt</th>
              <th className="py-1 pr-4">Win by 2</th>
              <th className="py-1 pr-4">Cap</th>
              <th className="py-1 pr-4">Games</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {formats.map((f) => (
              <tr key={f.id} className="border-t border-slate-100">
                <td className="py-1.5 pr-4">{f.round_number === null ? "All" : f.round_number}</td>
                <td className="py-1.5 pr-4">{f.points_to_win}</td>
                <td className="py-1.5 pr-4">{f.alt_points_to_win ?? "—"}</td>
                <td className="py-1.5 pr-4">{f.win_by_two ? "yes" : "no"}</td>
                <td className="py-1.5 pr-4">{f.hard_cap ?? "—"}</td>
                <td className="py-1.5 pr-4">{f.games_to_win_match}</td>
                <td className="py-1.5">
                  {f.round_number !== null && (
                    <button onClick={() => del(f.round_number!)} className="text-xs text-red-500 hover:underline">
                      remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <Field label="Round (blank=all)">
          <input
            className="w-24 rounded border border-slate-200 px-2 py-1"
            value={draft.round_number ?? ""}
            onChange={(e) => setDraft({ ...draft, round_number: e.target.value === "" ? null : Number(e.target.value) })}
            placeholder="all"
          />
        </Field>
        <Field label="Points">
          <input type="number" className="w-20 rounded border border-slate-200 px-2 py-1" value={draft.points_to_win} onChange={(e) => setDraft({ ...draft, points_to_win: Number(e.target.value) })} />
        </Field>
        <Field label="Alt points">
          <input type="number" className="w-20 rounded border border-slate-200 px-2 py-1" value={draft.alt_points_to_win ?? ""} onChange={(e) => setDraft({ ...draft, alt_points_to_win: e.target.value === "" ? null : Number(e.target.value) })} placeholder="none" />
        </Field>
        <label className="flex items-center gap-1.5 pb-1.5">
          <input type="checkbox" checked={draft.win_by_two} onChange={(e) => setDraft({ ...draft, win_by_two: e.target.checked })} />
          <span className="text-xs text-slate-600">Win by 2</span>
        </label>
        <Field label="Hard cap">
          <input type="number" className="w-20 rounded border border-slate-200 px-2 py-1" value={draft.hard_cap ?? ""} onChange={(e) => setDraft({ ...draft, hard_cap: e.target.value === "" ? null : Number(e.target.value) })} placeholder="none" />
        </Field>
        <Field label="Games to win">
          <input type="number" className="w-20 rounded border border-slate-200 px-2 py-1" value={draft.games_to_win_match} onChange={(e) => setDraft({ ...draft, games_to_win_match: Number(e.target.value) })} />
        </Field>
        <button onClick={save} className="bg-court text-white px-3 py-1.5 rounded text-sm">Save format</button>
        {msg && <span className="text-xs text-slate-500">{msg}</span>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-500">
      {label}
      {children}
    </label>
  );
}
