import { useCallback, useEffect, useState } from "react";
import { UserPlus, ShieldCheck, ShieldOff, RefreshCw } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { apiFetch } from "../lib/api.js";

/**
 * AdminUsersPage — экран управления пользователями (только для роли admin, под правом
 * users.manage). Список + создание + смена роли/блокировка. Все запросы через apiFetch
 * (cookie-сессия + CSRF). Бэкенд сам не даст убрать последнего админа (409).
 */
const ROLE_LABEL = { admin: "Админ", user: "Пользователь", vip: "VIP (безлимит)" };

export default function AdminUsersPage() {
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", password: "", role: "user" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    const r = await apiFetch("/api/users");
    if (r.ok) setUsers(await r.json());
    else setError("Не удалось загрузить пользователей");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createUser(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = new URLSearchParams(form);
      const r = await apiFetch("/api/users", { method: "POST", body });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.error || "Ошибка создания");
      }
      setForm({ username: "", password: "", role: "user" });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function patch(id, payload) {
    setError("");
    const r = await apiFetch(`/api/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      setError(j.error || "Не удалось изменить");
    }
    await load();
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <h1 className="text-xl font-bold text-ink">Пользователи</h1>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Создание */}
      <GlassCard className="p-5">
        <form onSubmit={createUser} className="flex flex-wrap items-end gap-3">
          <label className="flex-1 min-w-[10rem]">
            <span className="mb-1.5 block text-xs text-muted">Логин</span>
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              required
              className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-ink outline-none focus:border-brand/60 focus:ring-4 focus:ring-brand/20"
            />
          </label>
          <label className="flex-1 min-w-[10rem]">
            <span className="mb-1.5 block text-xs text-muted">Пароль (мин. 6)</span>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
              minLength={6}
              className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-ink outline-none focus:border-brand/60 focus:ring-4 focus:ring-brand/20"
            />
          </label>
          <label>
            <span className="mb-1.5 block text-xs text-muted">Роль</span>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-ink outline-none focus:border-brand/60"
            >
              <option value="user">Пользователь</option>
              <option value="vip">VIP (безлимит)</option>
              <option value="admin">Админ</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean px-4 py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60"
          >
            <UserPlus className="size-4" />
            Создать
          </button>
        </form>
      </GlassCard>

      {/* Список */}
      <GlassCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <span className="text-sm font-semibold text-muted">
            {users ? `${users.length} пользователей` : "Загрузка…"}
          </span>
          <button onClick={load} className="text-muted hover:text-ink" title="Обновить">
            <RefreshCw className="size-4" />
          </button>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="px-5 py-2 font-medium">Логин</th>
              <th className="px-5 py-2 font-medium">Роль</th>
              <th className="px-5 py-2 font-medium">Статус</th>
              <th className="px-5 py-2 font-medium">Последний вход</th>
              <th className="px-5 py-2" />
            </tr>
          </thead>
          <tbody>
            {(users || []).map((u) => (
              <tr key={u.id} className="border-t border-white/5">
                <td className="px-5 py-2.5 font-medium text-ink">{u.username}</td>
                <td className="px-5 py-2.5">
                  <select
                    value={u.role}
                    onChange={(e) => patch(u.id, { role: e.target.value })}
                    className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-ink outline-none focus:border-brand/60"
                  >
                    <option value="user">{ROLE_LABEL.user}</option>
                    <option value="vip">{ROLE_LABEL.vip}</option>
                    <option value="admin">{ROLE_LABEL.admin}</option>
                  </select>
                </td>
                <td className="px-5 py-2.5">
                  {u.is_active ? (
                    <span className="text-emerald-400">активен</span>
                  ) : (
                    <span className="text-muted">заблокирован</span>
                  )}
                </td>
                <td className="px-5 py-2.5 text-muted">
                  {u.last_login ? u.last_login.slice(0, 16).replace("T", " ") : "—"}
                </td>
                <td className="px-5 py-2.5 text-right">
                  <button
                    onClick={() => patch(u.id, { is_active: !u.is_active })}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted hover:bg-white/5 hover:text-ink"
                    title={u.is_active ? "Заблокировать" : "Разблокировать"}
                  >
                    {u.is_active ? <ShieldOff className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
                    {u.is_active ? "Блок" : "Вкл"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  );
}
