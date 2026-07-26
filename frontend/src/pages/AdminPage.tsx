import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bracket as BracketData, Category, api } from "../api";
import ScoringSettings from "../components/ScoringSettings";

interface AuthLike {
  isAdmin: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
  me: { email: string | null } | null;
}

interface ImportReport {
  imported: number;
  duplicates_dropped: number;
  skipped_invalid: number;
  per_category_counts: Record<string, number>;
  skipped: { row_number: number; reason: string }[];
  dropped_duplicates: { row_number: number; name: string; category: string }[];
}

export default function AdminPage({ auth }: { auth: AuthLike }) {
  const [params] = useSearchParams();
  if (auth.loading) return <div className="py-16 text-center text-slate-400">Loading…</div>;
  if (!auth.isAdmin) return <Login auth={auth} error={params.get("error")} />;
  return <AdminConsole auth={auth} />;
}

function Login({ auth, error }: { auth: AuthLike; error: string | null }) {
  const [devMsg, setDevMsg] = useState<string | null>(null);

  async function dev() {
    setDevMsg(null);
    try {
      await api.devLogin();
      await auth.refresh();
    } catch {
      setDevMsg("Dev login is disabled. Set ALLOW_DEV_LOGIN=true on the backend, or use Google.");
    }
  }

  return (
    <div className="max-w-md mx-auto mt-12 bg-white rounded-xl border border-slate-200 p-6 text-center">
      <h1 className="text-lg font-semibold text-slate-800">Admin sign in</h1>
      <p className="text-sm text-slate-500 mt-1">
        Only whitelisted Google accounts can enter scores and manage draws.
      </p>
      {error === "not_authorized" && (
        <div className="mt-3 text-sm text-red-600 bg-red-50 rounded px-3 py-2">
          That Google account is not on the admin whitelist.
        </div>
      )}
      <a
        href="/api/auth/login"
        className="mt-5 inline-block w-full bg-court text-white rounded-lg px-4 py-2 font-medium"
      >
        Sign in with Google
      </a>
      <div className="mt-4 text-xs text-slate-400">
        <button onClick={dev} className="underline">
          Use dev login (local only)
        </button>
        {devMsg && <div className="mt-2 text-slate-500">{devMsg}</div>}
      </div>
    </div>
  );
}

function AdminConsole({ auth }: { auth: AuthLike }) {
  const [category, setCategory] = useState<Category>("men");
  const [bracket, setBracket] = useState<BracketData | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [seed, setSeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadBracket = useCallback(async (cat: Category) => {
    setBracket(await api.bracket(cat));
  }, []);

  useEffect(() => {
    loadBracket(category);
  }, [category, loadBracket]);

  async function doImport() {
    const f = fileRef.current?.files?.[0];
    if (!f) {
      setMsg("Choose a CSV file first.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      setReport((await api.importCsv(f)) as ImportReport);
      await loadBracket(category);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    const t = bracket?.tournament;
    if (t && t.bracket_size) {
      if (
        !confirm(
          "A draw already exists. Regenerating will reshuffle and wipe all entered scores. Continue?",
        )
      )
        return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.generateDraw(category, seed === "" ? undefined : Number(seed));
      setMsg(`Draw generated: bracket ${r.bracket_size}, ${r.num_byes} byes, seed ${r.seed}.`);
      await loadBracket(category);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to generate.");
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    if (
      !confirm(
        "Locking freezes the bracket structure — you will no longer be able to regenerate the draw (scores can still be entered). Continue?",
      )
    )
      return;
    setBusy(true);
    setMsg(null);
    try {
      await api.lockDraw(category);
      setMsg("Draw locked.");
      await loadBracket(category);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to lock.");
    } finally {
      setBusy(false);
    }
  }

  const t = bracket?.tournament;
  const locked = t?.status === "locked";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-sm text-slate-500">
          Signed in as <span className="font-medium text-slate-700">{auth.me?.email}</span>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1">
          {(["men", "women"] as Category[]).map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-4 py-1.5 text-sm rounded-md ${
                category === c ? "bg-court text-white" : "text-slate-600"
              }`}
            >
              {c === "men" ? "Men's" : "Women's"}
            </button>
          ))}
        </div>
      </div>

      {msg && (
        <div className="text-sm bg-slate-100 text-slate-700 rounded px-3 py-2">{msg}</div>
      )}

      {/* CSV import */}
      <Section title="1. Import entries (CSV)">
        <div className="flex flex-wrap items-center gap-3">
          <input ref={fileRef} type="file" accept=".csv" className="text-sm" />
          <button
            onClick={doImport}
            disabled={busy}
            className="bg-court text-white px-3 py-1.5 rounded text-sm disabled:opacity-40"
          >
            Import
          </button>
          <span className="text-xs text-slate-400">
            Re-importing the same file is safe (idempotent).
          </span>
        </div>
        {report && (
          <div className="mt-3 text-sm">
            <div className="flex flex-wrap gap-4">
              <Stat label="Imported" value={report.imported} />
              <Stat label="Men" value={report.per_category_counts.men ?? 0} />
              <Stat label="Women" value={report.per_category_counts.women ?? 0} />
              <Stat label="Duplicates dropped" value={report.duplicates_dropped} />
              <Stat label="Skipped (invalid)" value={report.skipped_invalid} />
            </div>
            {(report.skipped.length > 0 || report.dropped_duplicates.length > 0) && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-slate-500">
                  View skipped / dropped rows
                </summary>
                <ul className="mt-2 text-xs text-slate-600 space-y-1">
                  {report.skipped.map((s) => (
                    <li key={`s${s.row_number}`}>
                      Row {s.row_number}: skipped — {s.reason}
                    </li>
                  ))}
                  {report.dropped_duplicates.map((d) => (
                    <li key={`d${d.row_number}`}>
                      Row {d.row_number}: duplicate of {d.name} ({d.category})
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </Section>

      {/* Draw */}
      <Section title="2. Generate & lock the draw">
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="RNG seed (optional)"
            className="w-40 rounded border border-slate-200 px-2 py-1 text-sm"
          />
          <button
            onClick={generate}
            disabled={busy || locked}
            className="bg-court text-white px-3 py-1.5 rounded text-sm disabled:opacity-40"
          >
            {t?.bracket_size ? "Regenerate draw" : "Generate draw"}
          </button>
          <button
            onClick={lock}
            disabled={busy || locked || !t?.bracket_size}
            className="border border-slate-300 text-slate-700 px-3 py-1.5 rounded text-sm disabled:opacity-40"
          >
            {locked ? "Locked" : "Lock draw"}
          </button>
          {t?.bracket_size ? (
            <span className="text-xs text-slate-500">
              Bracket {t.bracket_size}, {t.num_byes} byes, seed {t.draw_seed}, status {t.status}
            </span>
          ) : (
            <span className="text-xs text-slate-400">No draw yet.</span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-2">
          Enter scores directly on the bracket cards on the{" "}
          <a href="/" className="text-court underline">
            Brackets page
          </a>{" "}
          (editing is enabled while you are signed in).
        </p>
      </Section>

      {/* Scoring settings */}
      <Section title="3. Scoring settings">
        <ScoringSettings category={category} />
      </Section>

      {/* Admin management */}
      <Section title="4. Admins">
        <AdminList selfEmail={auth.me?.email ?? null} />
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-4">
      <h2 className="font-semibold text-slate-800 mb-3">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-lg font-semibold text-slate-800">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

function AdminList({ selfEmail }: { selfEmail: string | null }) {
  const [admins, setAdmins] = useState<{ id: number; email: string; added_by: string | null }[]>([]);
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAdmins(await api.listAdmins());
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to load admins.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    setMsg(null);
    try {
      await api.addAdmin(email.trim());
      setEmail("");
      load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed.");
    }
  }
  async function remove(id: number) {
    await api.removeAdmin(id);
    load();
  }

  return (
    <div className="space-y-3">
      <ul className="text-sm divide-y divide-slate-100">
        {admins.map((a) => (
          <li key={a.id} className="flex items-center justify-between py-1.5">
            <span>
              {a.email}
              {a.email === selfEmail && <span className="text-xs text-slate-400"> (you)</span>}
              {a.added_by && (
                <span className="text-xs text-slate-400"> — added by {a.added_by}</span>
              )}
            </span>
            {a.email !== selfEmail && (
              <button onClick={() => remove(a.id)} className="text-xs text-red-500 hover:underline">
                remove
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="new.admin@gmail.com"
          className="flex-1 rounded border border-slate-200 px-2 py-1 text-sm"
        />
        <button onClick={add} className="bg-court text-white px-3 py-1.5 rounded text-sm">
          Add admin
        </button>
      </div>
      {msg && <div className="text-xs text-red-500">{msg}</div>}
    </div>
  );
}
