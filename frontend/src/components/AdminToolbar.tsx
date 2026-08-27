import { useRef, useState } from "react";
import { ApiError, Category, Tournament, api } from "../api";
import ScoringSettings from "./ScoringSettings";
import MoveToGroupForm from "./MoveToGroupForm";

interface Props {
  tournament: Tournament | null;
  category: Category;
  onChanged: () => void;
}

const LEVELS = [
  "Nationals or States",
  "District or Local Tournaments",
  "School",
  "Casual",
  "No experience or Beginner",
];

export default function AdminToolbar({ tournament, category, onChanged }: Props) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(fn: () => Promise<any>, ok?: (r: any) => string) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      setMsg(ok ? ok(r) : "Done.");
      onChanged();
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : null;
      const text =
        typeof detail === "string"
          ? detail
          : detail && typeof detail === "object" && "message" in (detail as any)
            ? (detail as any).message
            : e instanceof Error
              ? e.message
              : "Failed.";
      setMsg(`Error: ${text}`);
    } finally {
      setBusy(false);
    }
  }

  const locked = tournament?.status === "locked";

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ToolbarBtn onClick={() => setOpen(open === "import" ? null : "import")}>Import CSV</ToolbarBtn>
        <ToolbarBtn onClick={() => setOpen(open === "walkin" ? null : "walkin")}>+ Walk-in player</ToolbarBtn>
        <ToolbarBtn onClick={() => setOpen(open === "move" ? null : "move")}>Move players to group</ToolbarBtn>
        {tournament && tournament.bracket_size ? (
          locked ? (
            <ToolbarBtn onClick={() => run(() => api.unlock(tournament.id), () => "Unlocked.")} disabled={busy}>
              Unlock this draw
            </ToolbarBtn>
          ) : (
            <ToolbarBtn
              onClick={() => confirm("Lock this draw? Structure can't be regenerated after (scores still editable).") && run(() => api.lock(tournament.id), () => "Locked.")}
              disabled={busy}
            >
              Lock this draw
            </ToolbarBtn>
          )
        ) : null}
        {tournament && tournament.bracket_size ? (
          <ToolbarBtn onClick={() => setOpen(open === "scoring" ? null : "scoring")}>Scoring settings</ToolbarBtn>
        ) : null}

        {/* Destructive redraws kept to the end — rarely needed after the initial build. */}
        <div className="w-px h-6 bg-slate-200 mx-1" />
        <ToolbarBtn
          onClick={() => confirm("Redraw the women's 128 bracket? This wipes current women's scores.") && run(() => api.rebuildWomen(), () => "Women's draw rebuilt.")}
          disabled={busy}
        >
          Rebuild women
        </ToolbarBtn>
        <ToolbarBtn
          onClick={() =>
            confirm("Rebuild the 4 men's groups and redraw all of them? This wipes current men's scores.") &&
            run(() => api.rebuildMen(), (r) => `Men rebuilt: ${JSON.stringify(r.groups && Object.fromEntries(Object.entries(r.groups).map(([k, v]: any) => [k, v.count])))}`)
          }
          disabled={busy}
        >
          Rebuild men (A–D)
        </ToolbarBtn>
        {msg && <span className="text-xs text-slate-500">{msg}</span>}
      </div>

      {open === "import" && (
        <Panel title="Import CSV" onClose={() => setOpen(null)}>
          <div className="flex flex-wrap items-center gap-3">
            <input ref={fileRef} type="file" accept=".csv" className="text-sm" />
            <button
              onClick={() => {
                const f = fileRef.current?.files?.[0];
                if (!f) return setMsg("Choose a CSV first.");
                run(() => api.importCsv(f), (r) => `Imported: ${JSON.stringify(r.per_category_counts)} · dupes ${r.duplicates_dropped} · skipped ${r.skipped_invalid}. Now rebuild the draws.`);
              }}
              disabled={busy}
              className="bg-court text-white px-3 py-1.5 rounded text-sm"
            >
              Upload & import
            </button>
            <span className="text-xs text-slate-400">Idempotent. After importing, click “Rebuild men” and “Rebuild women”.</span>
          </div>
        </Panel>
      )}

      {open === "walkin" && (
        <Panel title="Add walk-in player" onClose={() => setOpen(null)}>
          <WalkinForm category={category} onDone={(m) => { setMsg(m); onChanged(); }} />
        </Panel>
      )}

      {open === "move" && (
        <Panel title="Move players to group" onClose={() => setOpen(null)}>
          <MoveToGroupForm onDone={(m) => { setMsg(m); onChanged(); }} />
        </Panel>
      )}

      {open === "scoring" && tournament && (
        <Panel title="Scoring settings" onClose={() => setOpen(null)}>
          <ScoringSettings tournamentId={tournament.id} />
        </Panel>
      )}
    </div>
  );
}

function Panel({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="border-t border-slate-100 pt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{title}</span>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-full w-5 h-5 flex items-center justify-center text-sm leading-none"
          title="Close"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      {children}
    </div>
  );
}

function ToolbarBtn({ children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className="text-sm px-3 py-1.5 rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function WalkinForm({ category, onDone }: { category: Category; onDone: (msg: string) => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [experience, setExperience] = useState(LEVELS[3]);
  const [group, setGroup] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    try {
      const r = await api.walkin(category, {
        name,
        phone,
        experience,
        group_label: category === "men" ? group || null : null,
      });
      onDone(
        r.placed
          ? `Added ${name} to ${category === "men" ? "group " + r.group_label : "women"} and slotted into an open bye.`
          : `Added ${name} to the roster (no open bye slot — swap them in manually).`,
      );
      setName("");
      setPhone("");
    } catch (e: any) {
      onDone(typeof e?.detail === "object" ? e.detail.message : "Failed to add.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2 text-sm">
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} className="w-44 rounded border border-slate-200 px-2 py-1" />
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Phone
        <input value={phone} onChange={(e) => setPhone(e.target.value)} className="w-36 rounded border border-slate-200 px-2 py-1" />
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Level
        <select value={experience} onChange={(e) => setExperience(e.target.value)} className="rounded border border-slate-200 px-2 py-1">
          {LEVELS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </label>
      {category === "men" && (
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Group
          <select value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border border-slate-200 px-2 py-1">
            <option value="">Auto (smallest)</option>
            {["A", "B", "C", "D"].map((g) => (
              <option key={g}>{g}</option>
            ))}
          </select>
        </label>
      )}
      <button onClick={add} disabled={busy || !name.trim()} className="bg-court text-white px-3 py-1.5 rounded disabled:opacity-40">
        Add {category === "men" ? "man" : "woman"}
      </button>
    </div>
  );
}
