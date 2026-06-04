import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  History as HistoryIcon, Plane, Hotel, RotateCw, ChevronRight, Loader2, Search,
  CheckCircle2, AlertTriangle,
} from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { formatPrice, formatDate, formatDateTime, providerLabel } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { setRepeat } from "../lib/repeatStore.js";

/** Краткая сводка параметров прогона для заголовка строки истории. */
function summarize(p) {
  const hotels = p.search_mode === "hotels";
  const route = `${!hotels ? `${p.departure_city} → ` : ""}${p.destination_country}`;
  const kids = p.children_ages?.length ? ` + ${p.children_ages.length} реб.` : "";
  const nights = !hotels ? `, ${p.nights_min}–${p.nights_max} ноч.` : "";
  const detail = `${formatDate(p.date_from)}–${formatDate(p.date_to)}${nights}, ${p.adults} взр.${kids}`;
  return { hotels, route, detail };
}

/** HistoryPage — список прошлых прогонов (#/history): параметры + дата + «Повторить». */
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

  const repeat = (params) => {
    setRepeat(params);
    navigate("/"); // на странице поиска параметры подставятся и прогон запустится
  };

  return (
    <div className="mx-auto max-w-4xl">
      <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-4">
        <GlassCard variants={fadeUp} className="flex items-center gap-3 p-5">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <HistoryIcon className="size-5 text-white" />
          </span>
          <div>
            <h2 className="text-xl font-extrabold tracking-tight text-white">История прогонов</h2>
            <p className="text-xs text-muted">Параметры поиска и время — нажми, чтобы открыть отчёт</p>
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

        {runs && runs.map((r) => {
          const { hotels, route, detail } = summarize(r.params);
          return (
            <motion.div
              key={r.run_id}
              variants={fadeUp}
              className="glass-surface group flex items-center gap-3 rounded-xl2 p-4 shadow-glass transition-colors hover:border-brand/40"
            >
              {/* Основная область — открыть отчёт */}
              <div
                onClick={() => navigate(`/run/${r.run_id}`)}
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-3"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-sm font-bold text-brand-soft">
                  #{r.run_id}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                    {hotels ? <Hotel className="size-3.5 shrink-0 text-ocean" /> : <Plane className="size-3.5 shrink-0 text-ocean" />}
                    <span className="truncate">{route}</span>
                    <span className="shrink-0 rounded-full bg-brand/15 px-2 py-0.5 text-[10px] font-semibold text-brand-soft">
                      {hotels ? "Отели" : "Туры"}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-muted">{detail}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-muted/70">{formatDateTime(r.run_at)}</span>
                    {(r.provider_status ?? []).map((s) => (
                      <span
                        key={s.provider}
                        title={s.ok ? "успешно" : (s.error || "ошибка")}
                        className={[
                          "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold capitalize",
                          s.ok ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300",
                        ].join(" ")}
                      >
                        {s.ok ? <CheckCircle2 className="size-2.5" /> : <AlertTriangle className="size-2.5" />}
                        {providerLabel(s.provider)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="hidden shrink-0 text-right sm:block">
                  <div className="font-bold tabular-nums text-ink">{formatPrice(r.cheapest_price)}</div>
                  {r.cheapest_label && <div className="max-w-[140px] truncate text-[11px] text-muted">{r.cheapest_label}</div>}
                </div>
              </div>

              {/* Повторить прогон */}
              <button
                type="button"
                onClick={() => repeat(r.params)}
                title="Повторить этот поиск"
                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-muted transition-colors hover:border-brand/40 hover:text-ink"
              >
                <RotateCw className="size-3.5" /> Повторить
              </button>
              <ChevronRight className="hidden size-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-ink md:block" />
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}
