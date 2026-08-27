import { useState } from "react";
import { Category, api } from "../api";

interface Target { category: Category; group: string | null }

const PRESETS: { name: string; day: string; start: string; end: string; courts: string; targets: Target[] }[] = [
  {
    name: "Saturday — Men A & B",
    day: "Sat", start: "17:00", end: "20:30", courts: "Court 1, Court 2",
    targets: [{ category: "men", group: "A" }, { category: "men", group: "B" }],
  },
  {
    name: "Sunday — Men C & D",
    day: "Sun", start: "09:00", end: "17:00", courts: "Court 1, Court 2",
    targets: [{ category: "men", group: "C" }, { category: "men", group: "D" }],
  },
  {
    name: "Sunday — Women",
    day: "Sun", start: "09:00", end: "17:00", courts: "Court 3",
    targets: [{ category: "women", group: null }],
  },
];

export default function ScheduleForm({ onDone }: { onDone: (msg: string) => void }) {
  const [preset, setPreset] = useState(0);
  const [day, setDay] = useState(PRESETS[0].day);
  const [start, setStart] = useState(PRESETS[0].start);
  const [end, setEnd] = useState(PRESETS[0].end);
  const [courts, setCourts] = useState(PRESETS[0].courts);
  const [mins, setMins] = useState(12);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<any>(null);

  function choose(i: number) {
    const p = PRESETS[i];
    setPreset(i); setDay(p.day); setStart(p.start); setEnd(p.end); setCourts(p.courts);
    setReport(null);
  }

  const courtList = () => courts.split(",").map((c) => c.trim()).filter(Boolean);

  async function go() {
    setBusy(true); setReport(null);
    try {
      const r = await api.scheduleDay({
        targets: PRESETS[preset].targets,
        day_label: day, start, end,
        courts: courtList(),
        minutes_per_match: mins,
      });
      setReport(r);
      onDone(`Scheduled ${r.scheduled} of ${r.total_playable} matches.`);
    } catch (e: any) {
      const d = e?.detail;
      onDone(typeof d === "object" && d?.message ? d.message : "Scheduling failed.");
    } finally { setBusy(false); }
  }

  async function clear() {
    if (!confirm("Clear all match times for this group set?")) return;
    setBusy(true);
    try {
      const r = await api.clearSchedule(PRESETS[preset].targets);
      setReport(null);
      onDone(`Cleared ${r.cleared} match times.`);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p, i) => (
          <button key={p.name} onClick={() => choose(i)}
            className={`px-3 py-1.5 rounded-md border text-xs ${
              preset === i ? "bg-court text-white border-court" : "bg-white text-slate-600 border-slate-200"}`}>
            {p.name}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Day label"><input value={day} onChange={(e)=>setDay(e.target.value)} className="w-20 rounded border border-slate-200 px-2 py-1" /></Field>
        <Field label="Start (24h)"><input value={start} onChange={(e)=>setStart(e.target.value)} className="w-20 rounded border border-slate-200 px-2 py-1" /></Field>
        <Field label="End (24h)"><input value={end} onChange={(e)=>setEnd(e.target.value)} className="w-20 rounded border border-slate-200 px-2 py-1" /></Field>
        <Field label="Courts (comma separated)"><input value={courts} onChange={(e)=>setCourts(e.target.value)} className="w-56 rounded border border-slate-200 px-2 py-1" /></Field>
        <Field label="Min / match"><input type="number" value={mins} onChange={(e)=>setMins(Number(e.target.value))} className="w-20 rounded border border-slate-200 px-2 py-1" /></Field>
        <button onClick={go} disabled={busy} className="bg-court text-white px-3 py-1.5 rounded disabled:opacity-40">
          {busy ? "Scheduling…" : "Set times"}
        </button>
        <button onClick={clear} disabled={busy} className="border border-slate-300 text-slate-600 px-3 py-1.5 rounded">
          Clear times
        </button>
      </div>

      {report && (
        <div className="text-xs border-t border-slate-100 pt-2 space-y-1">
          <div className="text-slate-700">
            Scheduled <strong>{report.scheduled}</strong> of {report.total_playable} playable matches
            {report.finishes_by && <> · last match ends ~<strong>{report.finishes_by}</strong></>}
          </div>
          <div className="text-slate-500">
            Per round: {Object.entries(report.per_round).map(([r, n]) => `R${r}: ${n}`).join("  ")}
          </div>
          {report.unscheduled > 0 && (
            <div className="text-amber-700 bg-amber-50 rounded px-2 py-1">
              ⚠ {report.unscheduled} later-round matches have no time — the day only fits{" "}
              {report.slots_available} matches ({report.courts.length} court
              {report.courts.length > 1 ? "s" : ""} × {report.minutes_per_match} min). Add courts,
              extend hours, or shorten the match format to fit more.
            </div>
          )}
        </div>
      )}
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
