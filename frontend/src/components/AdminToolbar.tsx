import { useEffect, useRef, useState } from "react";
import { ApiError, Category, Tournament, api } from "../api";
import ScoringSettings from "./ScoringSettings";
import MoveToGroupForm from "./MoveToGroupForm";
import ScheduleForm from "./ScheduleForm";

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
  const [menuOpen, setMenuOpen] = useState(false);
  const menFileRef = useRef<HTMLInputElement>(null);
  const womenFileRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the menu on outside click or Escape (matters most on touch screens).
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  /** Open a panel from the menu, closing the menu itself. */
  function pick(panel: string) {
    setOpen((cur) => (cur === panel ? null : panel));
    setMenuOpen(false);
  }
  /** Run an action from the menu. */
  function act(fn: () => void) {
    setMenuOpen(false);
    fn();
  }

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

  function importMessage(category: Category, r: any) {
    const groups = r.explicit_men_groups ? Object.keys(r.explicit_men_groups) : [];
    if (category === "men" && groups.length) {
      return `Men imported: ${r.per_category_counts.men} · groups created: ${groups.map((g) => `Group ${g}`).join(", ")}.`;
    }
    if (category === "men") {
      return `Men imported: ${r.per_category_counts.men} · draw rebuilt.`;
    }
    return `Women imported: ${r.per_category_counts.women} · draw rebuilt.`;
  }

  function uploadCsv(category: Category, ref: React.RefObject<HTMLInputElement>) {
    const f = ref.current?.files?.[0];
    if (!f) return setMsg(`Choose a ${category === "men" ? "men's" : "women's"} CSV first.`);
    run(() => api.importCsv(f, category), (r) => importMessage(category, r));
  }

  const locked = tournament?.status === "locked";

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex items-center gap-2 text-sm px-3 py-2 rounded-md border border-slate-300 text-slate-700 bg-white hover:bg-slate-50"
          >
            Admin actions
            <span className={`text-[10px] transition-transform ${menuOpen ? "rotate-180" : ""}`}>▼</span>
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute left-0 mt-1 z-30 w-[min(20rem,calc(100vw-2rem))] bg-white border border-slate-200 rounded-lg shadow-lg py-1"
            >
              <MenuItem onClick={() => pick("import")} active={open === "import"}>Import CSV</MenuItem>
              <MenuItem onClick={() => pick("walkin")} active={open === "walkin"}>+ Walk-in player</MenuItem>
              <MenuItem onClick={() => pick("move")} active={open === "move"}>Move players to group</MenuItem>
              <MenuItem onClick={() => pick("sched")} active={open === "sched"}>Set match times</MenuItem>

              {tournament && tournament.bracket_size ? (
                <MenuItem onClick={() => pick("scoring")} active={open === "scoring"}>Scoring settings</MenuItem>
              ) : null}

              {tournament && tournament.bracket_size ? (
                <>
                  <div className="my-1 border-t border-slate-100" />
                  {locked ? (
                    <MenuItem
                      onClick={() => act(() => run(() => api.unlock(tournament.id), () => "Unlocked."))}
                      disabled={busy}
                    >
                      Unlock this draw
                    </MenuItem>
                  ) : (
                    <MenuItem
                      onClick={() =>
                        act(() => {
                          if (confirm("Lock this draw? Structure can't be regenerated after (scores still editable)."))
                            run(() => api.lock(tournament.id), () => "Locked.");
                        })
                      }
                      disabled={busy}
                    >
                      Lock this draw
                    </MenuItem>
                  )}
                </>
              ) : null}

              {/* Destructive redraws last — rarely needed once the event starts. */}
              <div className="my-1 border-t border-slate-100" />
              <div className="px-3 pt-1 pb-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                Danger zone
              </div>
              <MenuItem
                danger
                disabled={busy}
                onClick={() =>
                  act(() => {
                    if (confirm("Redraw the women's 128 bracket? This wipes current women's scores."))
                      run(() => api.rebuildWomen(), () => "Women's draw rebuilt.");
                  })
                }
              >
                Rebuild women
              </MenuItem>
              <MenuItem
                danger
                disabled={busy}
                onClick={() =>
                  act(() => {
                    if (confirm("Rebuild the 4 men's groups and redraw all of them? This wipes current men's scores."))
                      run(
                        () => api.rebuildMen(),
                        (r) =>
                          `Men rebuilt: ${JSON.stringify(
                            r.groups && Object.fromEntries(Object.entries(r.groups).map(([k, v]: any) => [k, v.count])),
                          )}`,
                      );
                  })
                }
              >
                Rebuild men (A–D)
              </MenuItem>
              <MenuItem
                danger
                disabled={busy}
                onClick={() =>
                  act(() => {
                    if (confirm("Clear all men's draws? This deletes all men's matches and unassigns their groups."))
                      run(
                        () => api.clearMenDraws(),
                        () => "Men's draws cleared and groups unassigned."
                      );
                  })
                }
              >
                Clear men's draws
              </MenuItem>
            </div>
          )}
        </div>

        <button
          onClick={() => setOpen((cur) => (cur === "import" ? null : "import"))}
          className={`text-sm px-3 py-2 rounded-md border ${
            open === "import" ? "bg-court text-white border-court" : "border-slate-300 text-slate-700 bg-white hover:bg-slate-50"
          }`}
        >
          Import CSV draw
        </button>

        {msg && <span className="text-xs text-slate-500 flex-1 min-w-0">{msg}</span>}
      </div>

      {open === "import" && (
        <Panel title="Import CSV draws" onClose={() => setOpen(null)}>
          <div className="grid gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="w-16 text-sm font-medium text-slate-700">Men</span>
              <input ref={menFileRef} type="file" accept=".csv" className="text-sm" />
              <button
                onClick={() => uploadCsv("men", menFileRef)}
                disabled={busy}
                className="bg-court text-white px-3 py-1.5 rounded text-sm"
              >
                Upload men CSV
              </button>
              <span className="text-xs text-slate-400">
                Blank lines create Group A, then Group B, and so on.
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="w-16 text-sm font-medium text-slate-700">Women</span>
              <input ref={womenFileRef} type="file" accept=".csv" className="text-sm" />
              <button
                onClick={() => uploadCsv("women", womenFileRef)}
                disabled={busy}
                className="bg-court text-white px-3 py-1.5 rounded text-sm"
              >
                Upload women CSV
              </button>
              <span className="text-xs text-slate-400">
                Imported into the women's main draw.
              </span>
            </div>
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

      {open === "sched" && (
        <Panel title="Set match times" onClose={() => setOpen(null)}>
          <ScheduleForm onDone={(m) => { setMsg(m); onChanged(); }} />
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

function MenuItem({
  children,
  active,
  danger,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; danger?: boolean }) {
  return (
    <button
      role="menuitem"
      {...rest}
      className={`w-full text-left px-3 py-2.5 text-sm disabled:opacity-40 ${
        danger ? "text-red-600 hover:bg-red-50" : "text-slate-700 hover:bg-slate-50"
      } ${active ? "bg-slate-100 font-medium" : ""}`}
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
