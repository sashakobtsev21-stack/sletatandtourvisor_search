import { m } from "framer-motion";
import { Palmtree, Search, Layers, History, FlaskConical, Users, CreditCard, LogOut, LogIn, UserPlus } from "lucide-react";
import { fadeUp } from "../lib/animations.js";
import { useAuth } from "../lib/auth.jsx";
import NotificationsBell from "./NotificationsBell.jsx";

/**
 * AppShell — общий каркас всех экранов дашборда: анимированный фон (световые
 * пятна для glassmorphism) + липкая шапка с навигацией по hash-маршрутам.
 * Вкладки фильтруются по правам текущего пользователя (`perm`); справа — кто вошёл
 * и кнопка выхода. Содержимое конкретной страницы передаётся через children.
 */
const NAV = [
  { label: "Поиск", href: "#/", icon: Search, perm: "search.run", match: (p) => p === "/" || p === "/search" || p.startsWith("/run") },
  // «Мультипоиск» (по многим направлениям) — только залогиненным (гость mode≠multiuser → скрыт).
  { label: "Мультипоиск", href: "#/batch", icon: Layers, perm: "search.run", mode: "multiuser", match: (p) => p.startsWith("/batch") || p.startsWith("/jobs") },
  { label: "История", href: "#/history", icon: History, perm: "history.view.own", match: (p) => p.startsWith("/history") },
  { label: "Автотесты", href: "#/tests", icon: FlaskConical, perm: "tests.view", match: (p) => p.startsWith("/tests") },
  // «Подписка» — только в мультиюзере (в локальном режиме оплата не нужна).
  { label: "Подписка", href: "#/billing", icon: CreditCard, mode: "multiuser", match: (p) => p.startsWith("/billing") },
  { label: "Пользователи", href: "#/admin/users", icon: Users, perm: "users.manage", match: (p) => p.startsWith("/admin/users") },
];

const ROLE_LABEL = { admin: "админ", user: "пользователь", vip: "VIP" };

export default function AppShell({ route = "/", children }) {
  const { user, can, logout } = useAuth();
  const isGuest = user?.mode === "guest";
  // У гостя корень «/» занят лендингом → вкладка «Поиск» ведёт в приложение на «/search».
  const nav = NAV
    .filter((n) => (!n.perm || can(n.perm)) && (!n.mode || user?.mode === n.mode))
    .map((n) => (n.label === "Поиск" && isGuest ? { ...n, href: "#/search" } : n));
  return (
    <div className="relative min-h-screen">
      {/* Анимированный градиентный фон путешествий (мягкие световые пятна) */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[42rem] animate-floatA rounded-full bg-brand/25 blur-[120px]" />
        <div className="absolute -right-40 top-1/4 size-[38rem] animate-floatB rounded-full bg-ocean/20 blur-[120px]" />
        <div className="absolute -bottom-48 left-1/3 size-[40rem] animate-floatA rounded-full bg-violet-500/15 blur-[120px]" />
      </div>

      {/* Шапка */}
      <m.header
        variants={fadeUp}
        initial="hidden"
        animate="show"
        className="glass-surface sticky top-0 z-30 border-x-0 border-t-0"
      >
        <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-3 px-5">
          <a href="#/" className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
              <Palmtree className="size-5 text-white" />
            </span>
            <div className="flex items-baseline gap-2">
              <span className="bg-gradient-to-r from-brand-soft to-ocean bg-clip-text text-lg font-extrabold tracking-tight text-transparent">
                Tour Search
              </span>
              <span className="hidden text-xs text-muted sm:inline">live-агрегатор туров</span>
            </div>
          </a>
          <nav className="ml-auto flex items-center gap-1 text-sm font-semibold text-muted">
            {nav.map(({ label, href, icon: Icon, match }) => {
              const active = match(route);
              return (
                <a
                  key={label}
                  href={href}
                  className={[
                    "flex items-center gap-1.5 rounded-lg px-3 py-2 transition-colors hover:bg-white/5 hover:text-ink",
                    active ? "bg-white/5 text-ink" : "",
                  ].join(" ")}
                >
                  <Icon className="size-4" />
                  <span className="hidden sm:inline">{label}</span>
                </a>
              );
            })}
          </nav>

          {/* Остаток поисков — плашка. Гость: «N бесплатных» → к регистрации; юзер: → «Подписка». */}
          {typeof user?.searches_left === "number" && (
            <a
              href={user.mode === "guest" ? "#/register" : "#/billing"}
              title={user.mode === "guest" ? "Бесплатные поиски — зарегистрируйтесь для 5" : "Осталось поисков — пополнить"}
              className={[
                "ml-2 hidden items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm font-semibold transition-colors sm:flex",
                user.searches_left > 0
                  ? "border-white/10 text-muted hover:bg-white/5 hover:text-ink"
                  : "border-amber-400/30 bg-amber-400/10 text-amber-300",
              ].join(" ")}
            >
              <CreditCard className="size-4" />
              {user.mode === "guest" ? `${user.searches_left} бесплатных` : `${user.searches_left} поиск.`}
            </a>
          )}

          {/* Колокольчик уведомлений — только залогиненным (гость/локальный режим — без). */}
          {user?.mode === "multiuser" && <NotificationsBell />}

          {/* Гость: войти / регистрация. Залогинен: имя + выход. Локальный режим: ничего. */}
          {user?.mode === "guest" ? (
            <div className="ml-2 flex items-center gap-2 border-l border-white/10 pl-3">
              <a
                href="#/login"
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-semibold text-muted transition-colors hover:bg-white/5 hover:text-ink"
              >
                <LogIn className="size-4" />
                <span className="hidden sm:inline">Войти</span>
              </a>
              <a
                href="#/register"
                className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-brand to-ocean px-3 py-2 text-sm font-semibold text-white shadow-glow transition-opacity hover:opacity-95"
              >
                <UserPlus className="size-4" />
                <span className="hidden sm:inline">Регистрация</span>
              </a>
            </div>
          ) : user?.username ? (
            <div className="ml-2 flex items-center gap-2 border-l border-white/10 pl-3">
              <div className="hidden text-right leading-tight sm:block">
                <div className="text-sm font-semibold text-ink">{user.username}</div>
                <div className="text-[11px] text-muted">{ROLE_LABEL[user.role] || user.role}</div>
              </div>
              <button
                onClick={logout}
                title="Выйти"
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-semibold text-muted transition-colors hover:bg-white/5 hover:text-ink"
              >
                <LogOut className="size-4" />
                <span className="hidden md:inline">Выход</span>
              </button>
            </div>
          ) : null}
        </div>
      </m.header>

      <main className="mx-auto max-w-[1800px] px-4 py-6 md:px-6">{children}</main>

      {/* Подпись автора (ненавязчивый водяной знак, не перехватывает клики) */}
      <div
        aria-hidden
        className="pointer-events-none fixed bottom-2.5 right-3 z-20 select-none font-mono text-[10.5px] tracking-wide text-white/30"
      >
        © Александр Кобцев
      </div>
    </div>
  );
}
