import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BracketFocus, Bracket as BracketData, Category, GroupSummary, api } from "./api";
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
  // Set when a search result asks to be shown in the draw; consumed by <Bracket>
  // once the right group's data has loaded.
  const [focus, setFocus] = useState<BracketFocus | null>(null);
  const focusNonce = useRef(0);
  const timer = useRef<number | null>(null);
  const selRef = useRef<Selection | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const stickyBarRef = useRef<HTMLDivElement | null>(null);

  const loadGroups = useCallback(async () => {
    try {
      setGroups(await api.groups());
    } catch {
      /* ignore */
    }
    // Flagged is admin-only server-side; skip the round-trip entirely for
    // public visitors instead of firing it and eating a guaranteed 401.
    if (auth.isAdmin) {
      try {
        setFlaggedCount((await api.flagged()).length);
      } catch {
        /* ignore */
      }
    }
  }, [auth.isAdmin]);

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
      const next = await api.bracket(s.category, s.group);
      // Ignore a stale response if the admin switched groups again mid-flight.
      if (selRef.current?.category === s.category && selRef.current?.group === s.group) {
        setData(next);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    selRef.current = sel;
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

  // Picking a group always shows that bracket, including from the Shortlist view.
  const pickGroup = useCallback((g: GroupSummary) => {
    setView("bracket");
    setSel(selectionFor(g));
  }, []);

  /** A search hit asked to be shown in the draw: switch to its group and hand
   * <Bracket> the tie to scroll to. The nonce makes picking the same match
   * twice re-trigger the scroll instead of being a no-op. */
  const showInBracket = useCallback(
    (category: Category, group: string | null, matchId?: number, playerId?: number) => {
      const g = groups.find((x) => x.category === category && x.group_label === group);
      if (g) pickGroup(g);
      setFocus(matchId ? { matchId, playerId: playerId ?? 0, nonce: ++focusNonce.current } : null);
    },
    [groups, pickGroup],
  );

  // The shortlist is admin-only; drop back to the bracket if an admin signs out.
  useEffect(() => {
    if (!auth.isAdmin && view === "flagged") setView("bracket");
  }, [auth.isAdmin, view]);

  /* Publish the height of the pinned header + toolbar stack as CSS variables.
   *
   * The bracket's mobile round tabs pin themselves directly beneath this stack,
   * and its height is genuinely variable — the admin toolbar appears and
   * disappears, the group tabs wrap differently per screen width, the login
   * panel opens. Measuring beats the magic number this used to rely on, which
   * was already a pixel off and would only have drifted further. */
  const measureStack = useCallback(() => {
    const header = headerRef.current?.offsetHeight ?? 0;
    const bar = stickyBarRef.current?.offsetHeight ?? 0;
    const root = document.documentElement;
    root.style.setProperty("--hdr-h", `${header}px`);
    root.style.setProperty("--stack-h", `${header + bar}px`);
  }, []);

  // Re-measure after every render. Everything that changes the bar's height —
  // groups arriving, the admin toolbar appearing, the login panel opening —
  // also re-renders App, so this keeps the offsets right on its own. That
  // matters because ResizeObserver below is driven by the rendering loop and
  // doesn't fire at all in a tab that isn't painting.
  useLayoutEffect(measureStack);

  // Belt and braces for the height changes App does NOT re-render for: a late
  // web font, rotating the phone, or a resize that re-wraps the group tabs.
  useEffect(() => {
    const ro = new ResizeObserver(measureStack);
    if (headerRef.current) ro.observe(headerRef.current);
    if (stickyBarRef.current) ro.observe(stickyBarRef.current);
    window.addEventListener("resize", measureStack);
    window.addEventListener("orientationchange", measureStack);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measureStack);
      window.removeEventListener("orientationchange", measureStack);
    };
  }, [measureStack]);

  const menGroups = useMemo(
    () => groups.filter((g) => g.category === "men").sort((a, b) => (a.group_label ?? "").localeCompare(b.group_label ?? "")),
    [groups],
  );
  const womenGroup = groups.find((g) => g.category === "women");

  const t = data?.tournament;

  return (
    <div className="min-h-screen flex flex-col">
      <header ref={headerRef} className="bg-white border-b border-slate-200 sticky top-0 z-20">
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
        {/* Search + group tabs + admin toolbar stay pinned while the bracket scrolls. */}
        <div
          ref={stickyBarRef}
          style={{ top: "var(--hdr-h, 57px)" }}
          className="sticky z-10 bg-slate-50 pt-1 pb-3 -mx-4 px-4 border-b border-slate-200"
        >
        {/* Player search */}
        <div className="mb-4">
          <SearchBar isAdmin={auth.isAdmin} onChanged={refresh} onPick={showInBracket} />
        </div>

        {/* Group navbar */}
        <div className="flex items-center gap-3 flex-wrap mb-4">
          <div className="flex items-center gap-1">
            <span className="text-xs font-semibold text-slate-400 uppercase mr-1">Men</span>
            {menGroups.map((g) => (
              <TabButton
                key={g.group_label}
                active={sel?.category === "men" && sel?.group === g.group_label}
                onClick={() => pickGroup(g)}
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
                onClick={() => pickGroup(womenGroup)}
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

        {view === "bracket" && auth.isAdmin && (
          <AdminToolbar tournament={t ?? null} category={sel?.category ?? "men"} onChanged={refresh} />
        )}
        </div>

        {view === "flagged" ? (
          <div className="mt-4">
            <div className="text-sm text-slate-500 mb-3">Shortlisted players (flagged ⭐ from the brackets)</div>
            <FlaggedList editable={auth.isAdmin} onChanged={refresh} />
          </div>
        ) : (
          <>
            {/* Keep the current bracket on screen while the next one loads, so
                switching groups never flashes an empty "Loading…" screen. */}
            {data ? (
              <div className={`mt-4 transition-opacity ${loading ? "opacity-60" : "opacity-100"}`}>
                <div className="text-sm text-slate-500 mb-2">
                  {sel?.category === "men" ? `Men's — Group ${sel?.group}` : "Women's"} · {data.players.length} players
                </div>
                <Bracket
                  data={data}
                  editable={auth.isAdmin}
                  onChanged={refresh}
                  onCountsChanged={loadGroups}
                  focus={focus}
                />
              </div>
            ) : (
              loading && <div className="py-16 text-center text-slate-400">Loading…</div>
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
