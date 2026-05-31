import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { History as HistoryIcon, Trophy, Zap, ChevronRight, Loader2, Search } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { formatPrice, formatDateTime } from "../lib/format.js";

/** HistoryPage — список прошлых прогонов (#/history) в стиле дашборда. */
export default function HistoryPage() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/runs")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => alive && setRuns(j))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mx-auto max-w-4xl">
      <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-4">
        <GlassCard variants={fadeUp} className="flex items-center gap-3 p-5">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <HistoryIcon className="size-5 text-white" />
          </span>
          <div>
            <h2 className="text-xl font-extrabold tracking-tight text-white">История прогонов</h2>
            <p className="text-xs text-muted">Последние сравнения — нажми, чтобы открыть отчёт</p>
          </div>
          <a href="#/" className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-brand-deep to-brand px-3.5 py-2 text-sm font-semibold text-white shadow-glow">
            <Search className="size-4" /> Новый поиск
          </a>
        </GlassCard>

        {error && (
          <GlassCard variants={fadeUp} className="p-6 text-sm text-rose-300">Не удалось загрузить историю: {error}</GlassCard>
        )}

        {!runs && !error && (
          <GlassCard variants={fadeUp} className="flex items-center justify-center gap-2 p-10 text-sm text-muted">
            <Loader2 className="size-4 animate-spin" /> Загружаю историю…
          </GlassCard>
        )}

        {runs && runs.length === 0 && (
          <GlassCard variants={fadeUp} className="p-10 text-center text-sm text-muted">
            Пока пусто — выполни первый поиск.
          </GlassCard>
        )}

        {runs && runs.map((r) => (
          <motion.a
            key={r.run_id}
            href={`#/run/${r.run_id}`}
            variants={fadeUp}
            whileHover={{ scale: 1.01, y: -1 }}
            className="glass-surface group flex items-center gap-4 rounded-xl2 p-4 shadow-glass transition-colors hover:border-brand/40"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-sm font-bold text-brand-soft">
              #{r.run_id}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Trophy className="size-3.5 shrink-0 text-emerald-300" />
                <span className="truncate">{r.cheapest_label || "нет результатов"}</span>
                {r.cheapest_provider && <span className="shrink-0 text-xs font-normal text-muted">({r.cheapest_provider})</span>}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
                <span>{formatDateTime(r.run_at)}</span>
                {r.fastest_provider && <span className="flex items-center gap-1"><Zap className="size-3" /> {r.fastest_provider}</span>}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-bold tabular-nums text-ink">{formatPrice(r.cheapest_price)}</div>
            </div>
            <ChevronRight className="size-4 shrink-0 text-muted transition-transform group-hover:translate-x-1 group-hover:text-ink" />
          </motion.a>
        ))}
      </motion.div>
    </div>
  );
}
