import { useState } from "react";

export default function LoginBar({
  onLogin,
  onDone,
}: {
  onLogin: (code: string, name: string) => Promise<void>;
  onDone: () => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setErr(null);
    setBusy(true);
    try {
      await onLogin(code, name || "admin");
      onDone();
    } catch (e: any) {
      setErr(typeof e?.detail === "string" ? e.detail : "Incorrect access code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-end gap-2 flex-wrap">
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Your name (for the log)
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Srijan"
          className="w-40 rounded border border-slate-200 px-2 py-1 text-sm"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Access code
        <input
          type="password"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          className="w-44 rounded border border-slate-200 px-2 py-1 text-sm"
        />
      </label>
      <button onClick={submit} disabled={busy} className="bg-court text-white px-3 py-1.5 rounded text-sm disabled:opacity-40">
        {busy ? "…" : "Sign in"}
      </button>
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  );
}
