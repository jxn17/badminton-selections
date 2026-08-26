import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bracket as BracketData, Category, GroupSummary, api } from "./api";
import { useAuth } from "./useAuth";
import Bracket from "./components/Bracket";
import AdminToolbar from "./components/AdminToolbar";
import LoginBar from "./components/LoginBar";
import FlaggedList from "./components/FlaggedList";
import SearchBar from "./components/SearchBar";

interface Selection {
  category: Category;
  group: string | null;
  label: string;
}

export default function App() {
  const auth = useAuth();
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [sel, setSel] = useState<Selection | null>(null);
  const [data, setData] = useState<BracketData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showLogin, setShowLogin] = useState(false);
  const [view, setView] = useState<"bracket" | "flagged">("bracket");
  const [flaggedCount, setFlaggedCount] = useState(0);
  const timer = useRef<number | null>(null);

  const loadGroups = useCallback(async () => {
    try {
      setGroups(await api.groups());
    } catch {
      /* ignore */
    }
    try {
      setFlaggedCount((await api.flagged()).length);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadGroups();
  }, [loadGroups]);

  // Default selection once groups load.
  useEffect(() => {
    if (sel || groups.length === 0) return;
    const men = groups.find((g) => g.category === "men");
    const first = men ?? groups[0];
    setSel(selectionFor(first));
  }, [groups, sel]);

  const loadBracket = useCallback(async (s: Selection) => {
    setLoading(true);
    try {
      setData(await api.bracket(s.category, s.group));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sel) loadBracket(sel);
  }, [sel, loadBracket]);

  // Live-ish refresh so multiple admins see each other's updates (every 15s).
  useEffect(() => {
    if (!sel) return;
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      api.bracket(sel.category, sel.group).then(setData).catch(() => {});
    }, 15000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [sel]);

  const refresh = useCallback(() => {
    if (sel) loadBracket(sel);
    loadGroups();
  }, [sel, loadBracket, loadGroups]);

  // The shortlist is admin-only; drop back to the bracket if an admin signs out.
  useEffect(() => {
    if (!auth.isAdmin && view === "flagged") setView("bracket");
  }, [auth.isAdmin, view]);

  const menGroups = useMemo(
    () => groups.filter((g) => g.category === "men").sort((a, b) => (a.group_label ?? "").localeCompare(b.group_label ?? "")),
    [groups],
  );
  const womenGroup = groups.find((g) => g.category === "women");

  const t = data?.tournament;

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-court text-xl">🏸</span>
            <span className="font-semibold text-slate-800">Badminton Trials 2026</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {auth.isAdmin ? (
              <>
                <span className="text-slate-500">
                  Admin: <span className="font-medium text-slate-700">{auth.name}</span>
                </span>
                <button onClick={auth.logout} className="px-3 py-1.5 rounded-md text-slate-600 hover:bg-slate-100">
                  Sign out
                </button>
              </>
            ) : (
              <button
                onClick={() => setShowLogin((v) => !v)}
                className="px-3 py-1.5 rounded-md border border-slate-300 text-slate-700"
              >
                Admin login
              </button>
            )}
          </div>
        </div>
        {showLogin && !auth.isAdmin && (
          <div className="border-t border-slate-100 bg-slate-50">
            <div className="max-w-7xl mx-auto px-4 py-3">
              <LoginBar onLogin={auth.login} onDone={() => setShowLogin(false)} />
            </div>
          </div>
        )}
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5">
        {/* Player search */}
        <div className="mb-4">
          <SearchBar
            isAdmin={auth.isAdmin}
            onChanged={refresh}
            onPick={(category, group) => {
              const g = groups.find((x) => x.category === category && x.group_label === group);
              if (g) {
                setView("bracket");
                setSel(selectionFor(g));
              }
            }}
          />
        </div>

        {/* Group navbar */}
        <div className="flex items-center gap-3 flex-wrap mb-4">
          <div className="flex items-center gap-1">
            <span className="text-xs font-semibold text-slate-400 uppercase mr-1">Men</span>
            {menGroups.map((g) => (
              <TabButton
                key={g.group_label}
                active={sel?.category === "men" && sel?.group === g.group_label}
                onClick={() => setSel(selectionFor(g))}
                locked={g.status === "locked"}
              >
                {g.group_label}
                <span className="ml-1 text-[10px] opacity-70">{g.player_count}</span>
              </TabButton>
            ))}
            {menGroups.length === 0 && <span className="text-xs text-slate-400">no draw yet</span>}
          </div>
          <div className="w-px h-6 bg-slate-200" />
          <div className="flex items-center gap-1">
            <span className="text-xs font-semibold text-slate-400 uppercase mr-1">Women</span>
            {womenGroup ? (
              <TabButton
                active={sel?.category === "women"}
                onClick={() => setSel(selectionFor(womenGroup))}
                locked={womenGroup.status === "locked"}
              >
                Main<span className="ml-1 text-[10px] opacity-70">{womenGroup.player_count}</span>
              </TabButton>
            ) : (
              <span className="text-xs text-slate-400">no draw yet</span>
            )}
          </div>

          {auth.isAdmin && (
            <>
              <div className="w-px h-6 bg-slate-200" />
              <button
                onClick={() => setView((v) => (v === "flagged" ? "bracket" : "flagged"))}
                className={`px-3 py-1.5 text-sm rounded-md border ${
                  view === "flagged" ? "bg-amber-400 text-white border-amber-400" : "bg-white text-slate-600 border-slate-200"
                }`}
              >
                ⭐ Shortlist<span className="ml-1 text-[10px] opacity-80">{flaggedCount}</span>
              </button>
            </>
          )}

          <div className="flex-1" />
          {view === "bracket" && t && t.bracket_size ? (
            <div className="text-xs text-slate-500 flex items-center gap-3">
              <span>Bracket {t.bracket_size}</span>
              <span>{t.num_byes} byes</span>
              <span className={`px-2 py-0.5 rounded-full ${t.status === "locked" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                {t.status}
              </span>
              {auth.isAdmin && <span className="px-2 py-0.5 rounded-full bg-court/10 text-court font-medium">editing</span>}
            </div>
          ) : null}
        </div>

        {view === "flagged" ? (
          <div className="mt-2">
            <div className="text-sm text-slate-500 mb-3">Shortlisted players (flagged ⭐ from the brackets)</div>
            <FlaggedList editable={auth.isAdmin} onChanged={refresh} />
          </div>
        ) : (
          <>
            {auth.isAdmin && (
              <AdminToolbar tournament={t ?? null} category={sel?.category ?? "men"} onChanged={refresh} />
            )}

            {loading && <div className="py-16 text-center text-slate-400">Loading…</div>}
            {!loading && data && (
              <div className="mt-4">
                <div className="text-sm text-slate-500 mb-2">
                  {sel?.category === "men" ? `Men's — Group ${sel?.group}` : "Women's"} · {data.players.length} players
                </div>
                <Bracket data={data} editable={auth.isAdmin} onChanged={refresh} />
              </div>
            )}
          </>
        )}
      </main>

      <footer className="text-center text-xs text-slate-400 py-4">
        Public view is read-only. Phone numbers are visible to signed-in admins only.
      </footer>
    </div>
  );
}

function selectionFor(g: GroupSummary): Selection {
  return {
    category: g.category,
    group: g.group_label,
    label: g.category === "men" ? `Men ${g.group_label}` : "Women",
  };
}

function TabButton({
  active,
  onClick,
  locked,
  children,
}: {
  active: boolean;
  onClick: () => void;
  locked?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-sm rounded-md border ${
        active ? "bg-court text-white border-court" : "bg-white text-slate-600 border-slate-200"
      }`}
    >
      {children}
      {locked && <span className="ml-1">🔒</span>}
    </button>
  );
}
