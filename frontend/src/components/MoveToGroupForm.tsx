import { useState } from "react";
import { api } from "../api";

/** Bulk-move players into groups, e.g. "everyone who can only come Sunday". */
export default function MoveToGroupForm({ onDone }: { onDone: (msg: string) => void }) {
  const [text, setText] = useState("");
  const [targets, setTargets] = useState<string[]>(["C", "D"]);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<any>(null);

  function toggle(g: string) {
    setTargets((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));
  }

  async function go() {
    // Accept whatever is pasted from WhatsApp: newlines, commas, +91, spaces.
    const phones = text
      .split(/[\n,;]+/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (phones.length === 0) return onDone("Paste at least one phone number.");
    if (targets.length === 0) return onDone("Pick at least one target group.");
    setBusy(true);
    setReport(null);
    try {
      const r = await api.moveToGroup(phones, targets);
      setReport(r);
      onDone(
        `Moved ${r.moved.length}, already there ${r.already_in_target.length}` +
          (r.not_found.length ? `, not found ${r.not_found.length}` : ""),
      );
    } catch (e: any) {
      const d = e?.detail;
      onDone(typeof d === "object" && d?.message ? d.message : "Move failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-slate-500 max-w-2xl">
        Paste phone numbers (one per line — straight from WhatsApp is fine; +91 and spaces are
        handled). Everyone listed is moved into the chosen group(s), swapping with players already
        there so group sizes stay equal. The affected groups are redrawn, so do this{" "}
        <strong>before</strong> any scores are entered.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={"+91 91009 37453\n+91 98851 60506"}
        className="w-full max-w-md rounded border border-slate-200 px-2 py-1 font-mono text-xs"
      />
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-slate-500">Into group:</span>
        {["A", "B", "C", "D"].map((g) => (
          <label key={g} className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={targets.includes(g)} onChange={() => toggle(g)} />
            {g}
          </label>
        ))}
        <button
          onClick={go}
          disabled={busy}
          className="bg-court text-white px-3 py-1.5 rounded text-sm disabled:opacity-40"
        >
          {busy ? "Moving…" : "Move players"}
        </button>
      </div>

      {report && (
        <div className="text-xs space-y-1 border-t border-slate-100 pt-2">
          {report.moved.map((m: any, i: number) => (
            <div key={i} className="text-slate-600">
              ✓ <strong>{m.name}</strong> {m.from} → {m.to}{" "}
              <span className="text-slate-400">(swapped with {m.swapped_with})</span>
            </div>
          ))}
          {report.already_in_target.map((m: any, i: number) => (
            <div key={`a${i}`} className="text-slate-400">
              • {m.name} already in {m.group}
            </div>
          ))}
          {report.not_found.map((p: string, i: number) => (
            <div key={`n${i}`} className="text-red-600">✗ not found: {p}</div>
          ))}
          {report.failed.map((f: any, i: number) => (
            <div key={`f${i}`} className="text-red-600">✗ {f.name}: {f.reason}</div>
          ))}
          {report.redrawn_groups?.length > 0 && (
            <div className="text-slate-500 pt-1">Redrawn: {report.redrawn_groups.join(", ")}</div>
          )}
        </div>
      )}
    </div>
  );
}
