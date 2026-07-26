import { useCallback, useEffect, useState } from "react";
import { api, Me } from "./api";

export function useAuth() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch {
      setMe({ authenticated: false, email: null, is_admin: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await api.logout();
    await refresh();
  }, [refresh]);

  return { me, loading, refresh, logout, isAdmin: !!me?.is_admin };
}
