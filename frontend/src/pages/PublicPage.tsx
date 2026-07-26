import { useCallback, useEffect, useState } from "react";
import { Bracket as BracketData, Category, api } from "../api";
import Bracket from "../components/Bracket";

interface AuthLike {
  isAdmin: boolean;
}

export default function PublicPage({ auth }: { auth: AuthLike }) {
  const [category, setCategory] = useState<Category>("men");
  const [data, setData] = useState<BracketData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (cat: Category) => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.bracket(cat));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load bracket.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(category);
  }, [category, load]);

  const t = data?.tournament;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
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
        {t && t.bracket_size ? (
          <div className="text-xs text-slate-500 flex items-center gap-3">
            <span>{data?.players.length} entries</span>
            <span>Bracket {t.bracket_size}</span>
            <span>{t.num_byes} byes</span>
            <span
              className={`px-2 py-0.5 rounded-full ${
                t.status === "locked"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              {t.status}
            </span>
            {auth.isAdmin && (
              <span className="px-2 py-0.5 rounded-full bg-court/10 text-court font-medium">
                editing on
              </span>
            )}
          </div>
        ) : null}
      </div>

      {loading && <div className="py-16 text-center text-slate-400">Loading…</div>}
      {error && <div className="py-8 text-center text-red-600">{error}</div>}
      {!loading && !error && data && (
        <Bracket
          data={data}
          category={category}
          editable={auth.isAdmin}
          onChanged={() => load(category)}
        />
      )}
    </div>
  );
}
