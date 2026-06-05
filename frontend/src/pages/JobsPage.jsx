import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Layers, Loader2, Plus, ChevronRight } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { apiFetch } from "../lib/api.js";

/** Человеческая метка и цвет статуса батча. */
const STATUS = {
  pending: { label: "в очереди", cls: "border-white/15 bg-white/5 text-muted" },
  running: { label: "идёт", cls: "border-ocean/40 bg-ocean/15 text-ocean" },
  done: { label: "готово", cls: "border-emerald-400/30 bg-emerald-500/15 text-emerald-200" },
  failed: { label: "ошибка", cls: "border-rose-400/30 bg-rose-500/15 text-rose-200" },
  interrupted: { label: "прервано", cls: "border-amber-400/30 bg-amber-400/10 text-amber-300" },
};

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
};

/**
 * JobsPage (#/jobs) — «Мои анализы»: список батч-заданий пользователя (статус, прогресс,
 * направления, дата). Клик открывает страницу прогресса/результата #/jobs/{id}.
 */
export default function JobsPage() {
  const [jobs, setJobs] = useState(null);

  useEffect(() => {
    let alive = true;
    apiFetch("/api/jobs")
      .then((r) => (r.ok ? r.json() : []))
      .then((j) => alive && setJobs(j))
      .catch(() => alive && setJobs([]));
    return () => { alive = false; };
  }, []);

  if (jobs === null)
    return (
      <div className="grid place-items-center py-20 text-muted">
        <Loader2 className="size-7 animate-spin" />
      </div>
    );

  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="mx-auto max-w-4xl space-y-4">
      <motion.div variants={fadeUp} className="flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
          <Layers className="size-5 text-white" />
        </span>
        <h2 className="text-xl font-extrabold tracking-tight text-white">Мои анализы</h2>
        <a href="#/batch" className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-brand to-ocean px-3 py-2 text-sm font-semibold text-white shadow-glow transition-opacity hover:opacity-95">
          <Plus className="size-4" /> Новый анализ
        </a>
      </motion.div>

      {jobs.length === 0 ? (
        <GlassCard variants={fadeUp} className="p-10 text-center text-sm text-muted">
          Анализов пока нет. Запустите первый — выберите несколько направлений на странице
          «Новый анализ».
        </GlassCard>
      ) : (
        jobs.map((j) => {
          const st = STATUS[j.status] ?? STATUS.pending;
          return (
            <GlassCard key={j.id} as={motion.a} variants={fadeUp} href={`#/jobs/${j.id}`} className="flex items-center gap-4 p-4 transition-colors hover:bg-white/[0.04]">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="font-bold text-white">Анализ #{j.id}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}>{st.label}</span>
                  <span className="text-xs text-muted">{fmtDate(j.created_at)}</span>
                </div>
                <div className="truncate text-sm text-muted">
                  {j.destinations.join(", ")}
                </div>
                {j.error && <div className="mt-1 text-xs text-amber-300/80">{j.error}</div>}
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm font-semibold tabular-nums text-ink">{j.progress_done}/{j.progress_total}</div>
                <div className="text-[11px] text-muted">направлений</div>
              </div>
              <ChevronRight className="size-4 shrink-0 text-muted" />
            </GlassCard>
          );
        })
      )}
    </motion.div>
  );
}
