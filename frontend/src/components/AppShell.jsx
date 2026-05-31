import { motion } from "framer-motion";
import { Palmtree, Search, History, FlaskConical } from "lucide-react";
import { fadeUp } from "../lib/animations.js";

/**
 * AppShell — общий каркас всех экранов дашборда: анимированный фон (световые
 * пятна для glassmorphism) + липкая шапка с навигацией по hash-маршрутам.
 * Содержимое конкретной страницы передаётся через children.
 */
const NAV = [
  { label: "Поиск", href: "#/", icon: Search, match: (p) => p === "/" || p.startsWith("/run") },
  { label: "История", href: "#/history", icon: History, match: (p) => p.startsWith("/history") },
  { label: "Автотесты", href: "#/tests", icon: FlaskConical, match: (p) => p.startsWith("/tests") },
];

export default function AppShell({ route = "/", children }) {
  return (
    <div className="relative min-h-screen">
      {/* Анимированный градиентный фон путешествий (мягкие световые пятна) */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[42rem] animate-floatA rounded-full bg-brand/25 blur-[120px]" />
        <div className="absolute -right-40 top-1/4 size-[38rem] animate-floatB rounded-full bg-ocean/20 blur-[120px]" />
        <div className="absolute -bottom-48 left-1/3 size-[40rem] animate-floatA rounded-full bg-violet-500/15 blur-[120px]" />
      </div>

      {/* Шапка */}
      <motion.header
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
                ТурСравнение
              </span>
              <span className="hidden text-xs text-muted sm:inline">live-агрегатор туров</span>
            </div>
          </a>
          <nav className="ml-auto flex items-center gap-1 text-sm font-semibold text-muted">
            {NAV.map(({ label, href, icon: Icon, match }) => {
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
        </div>
      </motion.header>

      <main className="mx-auto max-w-[1800px] px-4 py-6 md:px-6">{children}</main>
    </div>
  );
}
