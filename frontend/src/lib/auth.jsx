// Контекст авторизации: тянет /api/me, держит текущего пользователя и его права,
// даёт login/logout и хелпер can(perm). На 401 от любого apiFetch — сбрасывает в «гость»,
// и App покажет экран входа.
//
// Режимы бэкенда (см. docs/AUTH_PLAN.md): local → /api/me 200 со всеми правами (вход не
// нужен); multiuser → 200 после входа / 401 без; legacy → 200 если есть токен-cookie.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiFetch, setUnauthorizedHandler } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);   // { mode, username, role, permissions } | null
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/me");
      setUser(r.ok ? await r.json() : null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null)); // протухла сессия → показать вход
    refresh();
  }, [refresh]);

  const login = useCallback(
    async (username, password, remember) => {
      const body = new URLSearchParams({
        username, password, remember: remember ? "true" : "false",
      });
      const r = await apiFetch("/api/login", { method: "POST", body });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || "Не удалось войти");
      }
      await refresh(); // подтянуть роль/права из /api/me
    },
    [refresh]
  );

  const logout = useCallback(async () => {
    await apiFetch("/api/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  }, []);

  const can = useCallback(
    (perm) => Boolean(user && user.permissions && user.permissions.includes(perm)),
    [user]
  );

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, can, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
