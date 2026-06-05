import { useState } from "react";
import { motion } from "framer-motion";
import { Palmtree, User, Lock, LogIn } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { useAuth } from "../lib/auth.jsx";

/**
 * LoginPage — экран входа (режим всего приложения, не hash-маршрут). Показывается, когда
 * /api/me вернул 401 (мультиюзер без сессии). Тот же стеклянный стиль, что у дашборда.
 */
const control =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] py-2.5 pl-9 pr-3 text-sm text-ink " +
  "placeholder:text-muted/70 outline-none transition-all focus:border-brand/60 " +
  "focus:bg-white/[0.07] focus:ring-4 focus:ring-brand/20";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password, remember);
    } catch (err) {
      setError(err.message || "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center px-4">
      {/* фон как в AppShell */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[42rem] animate-floatA rounded-full bg-brand/25 blur-[120px]" />
        <div className="absolute -right-40 top-1/4 size-[38rem] animate-floatB rounded-full bg-ocean/20 blur-[120px]" />
      </div>

      <GlassCard
        as={motion.div}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="w-full max-w-sm p-7"
      >
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <Palmtree className="size-5 text-white" />
          </span>
          <div>
            <div className="bg-gradient-to-r from-brand-soft to-ocean bg-clip-text text-lg font-extrabold text-transparent">
              Tour Search
            </div>
            <div className="text-xs text-muted">Вход в систему</div>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="login-user" className="mb-1.5 block text-xs font-medium text-muted">
              Логин
            </label>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input
                id="login-user"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                className={control}
                placeholder="имя пользователя"
              />
            </div>
          </div>

          <div>
            <label htmlFor="login-pass" className="mb-1.5 block text-xs font-medium text-muted">
              Пароль
            </label>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input
                id="login-pass"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className={control}
                placeholder="••••••••"
              />
            </div>
          </div>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="size-4 rounded border-white/20 bg-white/5 accent-brand"
            />
            Запомнить меня
          </label>

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean py-2.5 text-sm font-semibold text-white shadow-glow transition-opacity hover:opacity-95 disabled:opacity-60"
          >
            <LogIn className="size-4" />
            {busy ? "Вхожу…" : "Войти"}
          </button>
        </form>
      </GlassCard>
    </div>
  );
}
