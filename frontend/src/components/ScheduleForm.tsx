import { useState } from "react";
import { Category, api } from "../api";

interface Target { category: Category; group: string | null }

interface Preset {
  name: string; day: string; start: string; end: string; courts: string;
  targets: Target[]; onlyUnscheduled?: boolean; note?: string;
}

const PRESETS: Preset[] = [
  {
    name: "Sat — Men A & B",
    day: "Sat", start: "17:00", end: "20:30", courts: "Court 1, Court 2",
    targets: [{ category: "men", group: "A" }, { category: "men", group: "B" }],
  },
  {
    name: "Sat — Women (court 3)",
    day: "Sat", start: "17:00", end: "20:30", courts: "Court 3",
    targets: [{ category: "women", group: null }],
    note: "Run this FIRST. Paste any player who can't make Saturday below — their matches are held for Sunday.",
  },
  {
    name: "Sun — Men C & D (+ A/B overflow)",
    day: "Sun", start: "09:00", end: "17:00", courts: "Court 1, Court 2",
    targets: [
      { category: "men", group: "A" },
      { category: "men", group: "B" },
      { category: "men", group: "C" },
      { category: "men", group: "D" },
    ],
    onlyUnscheduled: true,
    note:
      "Run this AFTER the Saturday A & B pass. Schedules C & D, plus any A/B " +
      "matches that didn't fit into Saturday — all on the same two courts, " +
      "earliest rounds first — without touching the times Saturday already set.",
  },
  {
    name: "Sun — Women (rest)",
    day: "Sun", start: "09:00", end: "17:00", courts: "Court 3",
    targets: [{ category: "women", group: null }], onlyUnscheduled: true,
    note: "Run this AFTER the Saturday women pass. Keeps Saturday's times and fills in everything left over.",
  },
];

export default function ScheduleForm({ onDone }: { onDone: (msg: string) => void }) {
  const [tab, setTab] = useState<"day" | "paste">("day");
  const [preset, setPreset] = useState(0);
  const [day, setDay] = useState(PRESETS[0].day);
  const [start, setStart] = useState(PRESETS[0].start);
  const [end, setEnd] = useState(PRESETS[0].end);
  const [courts, setCourts] = useState(PRESETS[0].courts);
  const [mins, setMins] = useState(8);
  const [unavailable, setUnavailable] = useState("");
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
        unavailable_phones: unavailable
          .split(/[\n,;]+/)
          .map((x) => x.trim())
          .filter(Boolean),
        only_unscheduled: !!PRESETS[preset].onlyUnscheduled,
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
      {/* Two distinct scheduling workflows: lay out a whole round vs. pin
          specific pasted players onto a time. */}
      <div className="flex gap-1 border-b border-slate-200">
        <button
          onClick={() => setTab("day")}
          className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px ${
            tab === "day" ? "border-court text-court" : "border-transparent text-slate-500"
          }`}
        >
          By group / day
        </button>
        <button
          onClick={() => setTab("paste")}
          className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px ${
            tab === "paste" ? "border-court text-court" : "border-transparent text-slate-500"
          }`}
        >
          Paste numbers
        </button>
      </div>

      {tab === "paste" && <SchedulePasteTab onDone={onDone} />}

      {tab === "day" && (
      <>
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p, i) => (
          <button key={p.name} onClick={() => choose(i)}
            className={`px-3 py-1.5 rounded-md border text-xs ${
              preset === i ? "bg-court text-white border-court" : "bg-white text-slate-600 border-slate-200"}`}>
            {p.name}
          </button>
        ))}
      </div>

      {PRESETS[preset].note && (
        <p className="text-xs text-slate-500 bg-slate-50 rounded px-2 py-1.5 max-w-2xl">
          {PRESETS[preset].note}
        </p>
      )}

      <Field label="Can't play this day (phone numbers, one per line) — optional">
        <textarea
          value={unavailable}
          onChange={(e) => setUnavailable(e.target.value)}
          rows={3}
          placeholder={"+91 90632 27011"}
          className="w-full max-w-md rounded border border-slate-200 px-2 py-1 font-mono text-xs"
        />
      </Field>

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
          {report.held_over > 0 && (
            <div className="text-slate-600">
              {report.held_over} match{report.held_over === 1 ? "" : "es"} held for another day
              (a player is unavailable).
            </div>
          )}
          {report.unknown_phones?.length > 0 && (
            <div className="text-red-600">Unknown phone(s): {report.unknown_phones.join(", ")}</div>
          )}
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
      </>
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

/** Paste any free text (a WhatsApp export, a list, whatever) — phone numbers
 * are auto-detected and each matched player's CURRENT match gets a time,
 * back to back on the given courts. For pinning down specific confirmed
 * players rather than laying out an entire round. */
function SchedulePasteTab({ onDone }: { onDone: (msg: string) => void }) {
  const [text, setText] = useState("");
  const [dayLabel, setDayLabel] = useState("Sat");
  const [start, setStart] = useState("16:00");
  const [courts, setCourts] = useState("Court 1, Court 2");
  const [mins, setMins] = useState(8);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<any>(null);

  async function go() {
    if (!text.trim()) return onDone("Paste some text with phone numbers in it first.");
    setBusy(true);
    setReport(null);
    try {
      const r = await api.scheduleSpecific({
        text,
        day_label: dayLabel,
        start,
        courts: courts.split(",").map((c) => c.trim()).filter(Boolean),
        minutes_per_match: mins,
      });
      setReport(r);
      onDone(`Scheduled ${r.scheduled.length} match${r.scheduled.length === 1 ? "" : "es"}.`);
    } catch (e: any) {
      const d = e?.detail;
      onDone(typeof d === "object" && d?.message ? d.message : "Scheduling failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500 max-w-2xl">
        Paste anything with phone numbers in it — a WhatsApp confirmation list, names and numbers,
        whatever you have. Numbers are found automatically; each matched player's current match
        (whoever they're due to play next) gets laid onto the courts below, back to back. If two
        pasted people are playing each other, that's one match, not two.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={"Confirmed for 4pm:\n1. Aarav Sharma +91 90632 27011\n2. Priya Singh 09876543210"}
        className="w-full max-w-md rounded border border-slate-200 px-2 py-1 font-mono text-xs"
      />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Day label">
          <input value={dayLabel} onChange={(e) => setDayLabel(e.target.value)} className="w-20 rounded border border-slate-200 px-2 py-1" />
        </Field>
        <Field label="Start (24h)">
          <input value={start} onChange={(e) => setStart(e.target.value)} className="w-20 rounded border border-slate-200 px-2 py-1" />
        </Field>
        <Field label="Courts (comma separated)">
          <input value={courts} onChange={(e) => setCourts(e.target.value)} className="w-56 rounded border border-slate-200 px-2 py-1" />
        </Field>
        <Field label="Min / match">
          <input type="number" value={mins} onChange={(e) => setMins(Number(e.target.value))} className="w-20 rounded border border-slate-200 px-2 py-1" />
        </Field>
        <button onClick={go} disabled={busy} className="bg-court text-white px-3 py-1.5 rounded text-sm disabled:opacity-40">
          {busy ? "Scheduling…" : "Schedule these players"}
        </button>
      </div>

      {report && (
        <div className="text-xs border-t border-slate-100 pt-2 space-y-1">
          {report.scheduled.map((s: any) => (
            <div key={s.match_id} className="text-slate-700">
              ✓ Match #{s.match_id} → <strong>{s.scheduled_time}</strong>
            </div>
          ))}
          {report.no_active_match?.length > 0 && (
            <div className="text-amber-700">
              No current match to schedule for: {report.no_active_match.join(", ")} (already
              finished, eliminated, or opponent not decided yet).
            </div>
          )}
          {report.not_found?.length > 0 && (
            <div className="text-red-600">Not recognized as a registered player: {report.not_found.join(", ")}</div>
          )}
          {report.finishes_by && (
            <div className="text-slate-500">Last of these ends ~{report.finishes_by}</div>
          )}
        </div>
      )}
    </div>
  );
}
