import { useCallback, useEffect, useState } from "react";
import { Category, RoundFormat, api } from "../api";

const EMPTY: Omit<RoundFormat, "id"> = {
  round_number: null,
  points_to_win: 15,
  win_by_two: true,
  hard_cap: null,
  games_to_win_match: 1,
};

export default function ScoringSettings({ category }: { category: Category }) {
  const [formats, setFormats] = useState<RoundFormat[]>([]);
  const [draft, setDraft] = useState<Omit<RoundFormat, "id">>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setFormats(await api.listFormats(category));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to load formats.");
    }
  }, [category]);

  useEffect(() => {
    load();
    setDraft(EMPTY);
  }, [load]);

  async function save() {
    setMsg(null);
    try {
      await api.upsertFormat(category, draft);
      setMsg("Saved.");
      setDraft(EMPTY);
      load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to save.");
    }
  }

  async function del(roundNumber: number) {
    await api.deleteFormat(category, roundNumber);
    load();
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        The default (Round = <em>all</em>) applies everywhere; add a row with a specific
        round number to override just that round.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pr-3">Round</th>
              <th className="py-1 pr-3">Points</th>
              <th className="py-1 pr-3">Win by 2</th>
              <th className="py-1 pr-3">Hard cap</th>
              <th className="py-1 pr-3">Games to win</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {formats.map((f) => (
              <tr key={f.id} className="border-t border-slate-100">
                <td className="py-1.5 pr-3">{f.round_number === null ? "All (default)" : f.round_number}</td>
                <td className="py-1.5 pr-3">{f.points_to_win}</td>
                <td className="py-1.5 pr-3">{f.win_by_two ? "yes" : "no"}</td>
                <td className="py-1.5 pr-3">{f.hard_cap ?? "—"}</td>
                <td className="py-1.5 pr-3">{f.games_to_win_match}</td>
                <td className="py-1.5">
                  {f.round_number !== null && (
                    <button
                      onClick={() => del(f.round_number!)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-slate-200 p-3 bg-slate-50 space-y-3">
        <div className="text-sm font-medium text-slate-700">Add / update a format</div>
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Round (blank = default)</span>
            <input
              className="w-28 rounded border border-slate-200 px-2 py-1"
              value={draft.round_number ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  round_number: e.target.value === "" ? null : Number(e.target.value),
                })
              }
              placeholder="all"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Points to win</span>
            <input
              type="number"
              className="w-24 rounded border border-slate-200 px-2 py-1"
              value={draft.points_to_win}
              onChange={(e) => setDraft({ ...draft, points_to_win: Number(e.target.value) })}
            />
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.win_by_two}
              onChange={(e) => setDraft({ ...draft, win_by_two: e.target.checked })}
            />
            <span className="text-xs text-slate-600">Win by two</span>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Hard cap</span>
            <input
              type="number"
              className="w-24 rounded border border-slate-200 px-2 py-1"
              value={draft.hard_cap ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  hard_cap: e.target.value === "" ? null : Number(e.target.value),
                })
              }
              placeholder="none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Games to win match</span>
            <input
              type="number"
              className="w-24 rounded border border-slate-200 px-2 py-1"
              value={draft.games_to_win_match}
              onChange={(e) =>
                setDraft({ ...draft, games_to_win_match: Number(e.target.value) })
              }
            />
          </label>
          <button onClick={save} className="bg-court text-white px-3 py-1.5 rounded text-sm">
            Save
          </button>
        </div>
        {msg && <div className="text-xs text-slate-500">{msg}</div>}
      </div>
    </div>
  );
}
