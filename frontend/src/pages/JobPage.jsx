import { useEffect, useRef, useState } from "react";
import { m } from "framer-motion";
import { Layers, Loader2, AlertTriangle, CheckCircle2, Clock, ExternalLink, ArrowLeft } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { formatPrice } from "../lib/format.js";
import { apiFetch } from "../lib/api.js";

const JOB_STATUS = {
  pending: { label: "в очереди", cls: "border-white/15 bg-white/5 text-muted" },
  running: { label: "идёт мультипоиск", cls: "border-ocean/40 bg-ocean/15 text-ocean" },
  done: { label: "готово", cls: "border-emerald-400/30 bg-emerald-500/15 text-emerald-200" },
  failed: { label: "ошибка", cls: "border-rose-400/30 bg-rose-500/15 text-rose-200" },
  interrupted: { label: "прервано", cls: "border-amber-400/30 bg-amber-400/10 text-amber-300" },
};

/**
 * JobPage (#/jobs/{id}) — прогресс и результат батч-анализа. Пока задание идёт — опрашиваем
 * GET /api/jobs/{id} каждые 3с; по завершении поллинг останавливается. Деталь направления —
 * существующая страница результатов прогона (#/run/{runId}).
 */
export default function JobPage({ jobId }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let alive = true;
    let fails = 0;
    // audit-3 P3: AbortController отменяет in-flight fetch при unmount.
    // Раньше fetch жил до тайм-аута (~30с) после ухода со страницы — занимал
    // TCP-соединение впустую, мог тригернуть state-обновление (alive=false спасал
    // от краша, но не от утечки сокета).
    const ctrl = new AbortController();
    const schedule = () => { timerRef.current = setTimeout(tick, 3000); };
    const tick = async () => {
      try {
        const r = await apiFetch(`/api/jobs/${jobId}`,
                                 { retry: false, signal: ctrl.signal });
        if (r.status === 404 || r.status === 403) {  // постоянная ошибка (нет/чужой) → сразу
          if (alive) setError(`HTTP ${r.status}`);
          return;
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);   // сеть/5xx → транзиторно, ретраим
        const j = await r.json();
        if (!alive) return;
        fails = 0;
        setError(null);
        setJob(j);
        if (j.status === "pending" || j.status === "running") schedule();
      } catch (e) {
        if (!alive || e?.name === "AbortError") return;     // unmount → не state-апдейтим
        // Одна сетевая икота не должна навсегда заморозить прогресс: ретраим, пока не
        // накопится несколько подряд — только тогда показываем ошибку.
        fails += 1;
        if (fails >= 4) setError(String(e));
        else schedule();
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timerRef.current);
      ctrl.abort();                                          // отменяем in-flight
    };
  }, [jobId]);

  if (error)
    return <Center icon={AlertTriangle} tone="err" text={`Не удалось загрузить мультипоиск #${jobId}: ${error}`} />;
  if (!job)
    return <Center icon={Loader2} spin text={`Загружаю мультипоиск #${jobId}…`} />;

  const st = JOB_STATUS[job.status] ?? JOB_STATUS.pending;
  const pct = job.progress_total ? Math.round((job.progress_done / job.progress_total) * 100) : 0;

  return (
    <m.div variants={staggerContainer} initial="hidden" animate="show" className="mx-auto max-w-4xl space-y-4">
      <GlassCard variants={fadeUp} className="p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <Layers className="size-5 text-white" />
          </span>
          <h2 className="text-xl font-extrabold tracking-tight text-white">Мультипоиск #{job.id}</h2>
          <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${st.cls}`}>{st.label}</span>
          <a href="#/jobs" className="ml-auto flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-muted transition-colors hover:text-ink">
            <ArrowLeft className="size-4" /> Все мультипоиски
          </a>
        </div>

        {/* Прогресс */}
        <div className="mt-4">
          <div className="mb-1.5 flex justify-between text-xs text-muted">
            <span>Готово направлений: {job.progress_done} из {job.progress_total}</span>
            <span className="tabular-nums">{pct}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-white/10">
            <m.div
              className="h-full rounded-full bg-gradient-to-r from-brand to-ocean"
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.4 }}
            />
          </div>
        </div>
        {job.error && <p className="mt-3 text-sm text-amber-300/90">{job.error}</p>}
      </GlassCard>

      {/* Направления */}
      <div className="space-y-2">
        {job.directions.map((d) => (
          <GlassCard key={d.country} variants={fadeUp} className="flex items-center gap-3 p-4">
            <DirIcon status={d.status} />
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-white">{d.country}</div>
              {d.status === "done" && d.cheapest_price ? (
                <div className="truncate text-sm text-muted">
                  Лучшее: <span className="font-semibold text-emerald-300">{formatPrice(d.cheapest_price)}</span>
                  {d.cheapest_label ? ` — ${d.cheapest_label}` : ""}
                  {d.cheapest_provider ? ` (${d.cheapest_provider})` : ""}
                </div>
              ) : (
                <div className="text-sm text-muted">{DIR_LABEL[d.status] ?? "—"}</div>
              )}
            </div>
            {d.run_id != null && (
              <a href={`#/run/${d.run_id}`} className="flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-ocean transition-colors hover:text-brand-soft">
                <ExternalLink className="size-3.5" /> Открыть
              </a>
            )}
          </GlassCard>
        ))}
      </div>
    </m.div>
  );
}

const DIR_LABEL = { done: "готово", pending: "в очереди / идёт", failed: "не удалось" };

function DirIcon({ status }) {
  if (status === "done") return <CheckCircle2 className="size-5 shrink-0 text-emerald-400" />;
  if (status === "failed") return <AlertTriangle className="size-5 shrink-0 text-rose-400" />;
  return <Clock className="size-5 shrink-0 text-muted" />;
}

function Center({ icon: Icon, text, spin = false, tone }) {
  return (
    <div className="mx-auto max-w-2xl">
      <GlassCard className="p-10">
        <div className={`flex flex-col items-center gap-3 text-center ${tone === "err" ? "text-rose-300" : "text-muted"}`}>
          <Icon className={`size-8 ${spin ? "animate-spin" : ""}`} />
          <p className="text-sm">{text}</p>
          <a href="#/jobs" className="mt-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-ink hover:bg-white/[0.07]">
            ← Мои мультипоиски
          </a>
        </div>
      </GlassCard>
    </div>
  );
}
