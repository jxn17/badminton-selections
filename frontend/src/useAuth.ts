import { useCallback, useEffect, useState } from "react";
import { Me, api } from "./api";

export function useAuth() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch {
      setMe({ is_admin: false, name: null });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(
    async (code: string, name: string) => {
      await api.codeLogin(code, name);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await api.logout();
    await refresh();
  }, [refresh]);

  return { me, loading, refresh, login, logout, isAdmin: !!me?.is_admin, name: me?.name ?? null };
}
