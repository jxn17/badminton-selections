import { Link, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";
import PublicPage from "./pages/PublicPage";
import AdminPage from "./pages/AdminPage";

export default function App() {
  const auth = useAuth();
  const loc = useLocation();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="text-court text-xl">🏸</span>
            <span className="font-semibold text-slate-800 leading-tight">
              Team Selection <span className="hidden sm:inline text-slate-400">/ 2026–27</span>
            </span>
          </Link>
          <nav className="flex items-center gap-2 text-sm">
            <Link
              to="/"
              className={`px-3 py-1.5 rounded-md ${
                loc.pathname === "/" ? "bg-slate-100 font-medium" : "text-slate-600"
              }`}
            >
              Brackets
            </Link>
            <Link
              to="/admin"
              className={`px-3 py-1.5 rounded-md ${
                loc.pathname.startsWith("/admin")
                  ? "bg-slate-100 font-medium"
                  : "text-slate-600"
              }`}
            >
              Admin
            </Link>
            {auth.isAdmin && (
              <button
                onClick={auth.logout}
                className="px-3 py-1.5 rounded-md text-slate-600 hover:bg-slate-100"
              >
                Sign out
              </button>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<PublicPage auth={auth} />} />
          <Route path="/admin" element={<AdminPage auth={auth} />} />
        </Routes>
      </main>

      <footer className="text-center text-xs text-slate-400 py-4">
        Public view is read-only. Scores are entered by tournament admins.
      </footer>
    </div>
  );
}
