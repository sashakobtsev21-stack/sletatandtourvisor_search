import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Trophy, Zap, Turtle, Hotel, Plane, ArrowLeft, ImageIcon,
  ExternalLink, AlertTriangle, Loader2, Star,
} from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { formatPrice, formatDate } from "../lib/format.js";

/** ResultsPage — отчёт сравнения одного прогона (#/run/{id}) в стиле дашборда. */
export default function ResultsPage({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [shot, setShot] = useState(null); // {src, cap} для модалки скриншота
  const [zoom, setZoom] = useState(false); // приближён ли скриншот в модалке

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    fetch(`/api/runs/${runId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => alive && setData(j))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [runId]);

  if (error) return <CenterCard icon={AlertTriangle} tone="err" text={`Не удалось загрузить прогон #${runId}: ${error}`} back />;
  if (!data) return <CenterCard icon={Loader2} spin text={`Загружаю прогон #${runId}…`} />;

  const p = data.params;
  const hotels = p.search_mode === "hotels";

  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="mx-auto max-w-5xl space-y-5">
      {/* Заголовок + сводка */}
      <GlassCard variants={fadeUp} className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-brand-deep shadow-glow">
            {hotels ? <Hotel className="size-5 text-white" /> : <Plane className="size-5 text-white" />}
          </span>
          <div>
            <h2 className="text-xl font-extrabold tracking-tight text-white">
              Результат сравнения
              <span className="ml-2 rounded-full bg-brand/20 px-2.5 py-0.5 align-middle text-xs font-semibold text-brand-soft">
                {hotels ? "Отели" : "Туры"}
              </span>
            </h2>
            <p className="text-xs text-muted">
              {!hotels && `${p.departure_city} → `}{p.destination_country}, {formatDate(p.date_from)}–{formatDate(p.date_to)}
              {!hotels && `, ${p.nights_min}–${p.nights_max} ноч.`}, {p.adults} взр.
              {p.children_ages.length > 0 && ` + ${p.children_ages.length} реб.`}
              {data.run_id != null && ` · прогон #${data.run_id}`}
            </p>
          </div>
          <a href="#/" className="ml-auto flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-muted transition-colors hover:text-ink">
            <ArrowLeft className="size-4" /> Новый поиск
          </a>
        </div>

        {/* Таблица площадок */}
        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-muted">
                <th className="py-2 pr-3 font-semibold">Площадка</th>
                <th className="py-2 pr-3 font-semibold">Время</th>
                <th className="py-2 pr-3 font-semibold">Мин. цена</th>
                <th className="py-2 pr-3 font-semibold">Лучшее предложение</th>
                <th className="py-2 font-semibold">Выдача</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.provider} className="border-b border-white/5">
                  <td className="py-2.5 pr-3 font-semibold capitalize text-ink">{r.provider}</td>
                  <td className="py-2.5 pr-3 tabular-nums text-muted">{r.success ? `${r.duration_seconds.toFixed(1)} с` : "—"}</td>
                  <td className="py-2.5 pr-3 font-semibold tabular-nums text-ink">{r.cheapest ? formatPrice(r.cheapest.price, r.cheapest.currency) : "—"}</td>
                  <td className="py-2.5 pr-3">
                    {r.success ? (
                      <span className="text-ink">{r.cheapest ? r.cheapest.label : "нет результатов"}</span>
                    ) : (
                      <span className="text-rose-300">{r.error || "ошибка"}</span>
                    )}
                  </td>
                  <td className="py-2.5">
                    <div className="flex items-center gap-3">
                      {r.screenshot_path ? (
                        <button
                          type="button"
                          onClick={() => { setZoom(false); setShot({ src: `/${r.screenshot_path}`, cap: `${r.provider} — выдача` }); }}
                          className="flex items-center gap-1 text-ocean transition-colors hover:text-brand-soft"
                        >
                          <ImageIcon className="size-3.5" /> скриншот
                        </button>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                      {r.search_url && (
                        <a href={r.search_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-ocean transition-colors hover:text-brand-soft">
                          <ExternalLink className="size-3.5" /> поиск
                        </a>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Итоги */}
        <div className="mt-4 flex flex-wrap gap-2">
          {data.best && (
            <Badge tone="best" icon={Trophy}>
              Лучшее: {formatPrice(data.best.price)} — {data.best.label} ({data.best.provider})
            </Badge>
          )}
          {data.fastest_provider && (
            <Badge tone="info" icon={Zap}>Быстрее всех: {data.fastest_provider}</Badge>
          )}
          {data.slowest_provider && data.slowest_provider !== data.fastest_provider && (
            <Badge tone="muted" icon={Turtle}>Медленнее: {data.slowest_provider}</Badge>
          )}
        </div>
      </GlassCard>

      {/* Детальные карточки площадок */}
      <div className="grid gap-5 md:grid-cols-2">
        {data.results.map((r) => (
          <GlassCard key={r.provider} variants={fadeUp} className="p-5">
            <h3 className="mb-3 flex items-center gap-2 text-base font-bold text-white">
              <span className="capitalize">{r.provider}</span>
              {r.success && <span className="text-xs font-normal text-muted">({r.duration_seconds.toFixed(1)} с)</span>}
            </h3>
            {!r.success ? (
              <p className="text-sm text-rose-300">⚠️ {r.error || "поиск не дал результатов"}</p>
            ) : (
              <div className="space-y-4">
                {r.hotel_offers.length > 0 && (
                  <ProviderTable
                    head={["Отель", "★", "Рейтинг", "Цена"]}
                    rows={r.hotel_offers.map((h) => [
                      h.hotel_name,
                      h.stars ? <Stars n={h.stars} /> : "—",
                      h.rating ?? "—",
                      formatPrice(h.price, h.currency),
                    ])}
                  />
                )}
                {r.operator_offers?.length > 0 && (
                  <div>
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
                      Туроператоры
                    </h4>
                    <ProviderTable
                      head={["Оператор", "Цена", "Скорость"]}
                      rows={r.operator_offers.map((o) => [
                        o.operator,
                        formatPrice(o.price, o.currency),
                        o.load_seconds != null ? `${o.load_seconds} с` : "—",
                      ])}
                    />
                  </div>
                )}
                {r.hotel_offers.length === 0 && (r.operator_offers?.length ?? 0) === 0 && (
                  <p className="text-sm text-muted">Предложений не найдено.</p>
                )}
              </div>
            )}
          </GlassCard>
        ))}
      </div>

      {/* Модалка скриншота — с приближением (клик по фото) */}
      <AnimatePresence>
        {shot && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setShot(null)}
            className="fixed inset-0 z-50 overflow-auto bg-black/90 p-4"
          >
            <div className="pointer-events-none sticky top-0 z-10 pb-2 text-center text-sm text-white/80">
              {shot.cap} · клик по изображению — {zoom ? "отдалить" : "приблизить"}, клик по фону — закрыть
            </div>
            <div className={`flex min-h-full ${zoom ? "items-start justify-start" : "items-center justify-center"}`}>
              <img
                src={shot.src} alt={shot.cap}
                onClick={(e) => { e.stopPropagation(); setZoom((z) => !z); }}
                className={
                  zoom
                    ? "max-w-none cursor-zoom-out rounded-lg shadow-2xl"
                    : "max-h-[88vh] max-w-[94vw] cursor-zoom-in rounded-lg object-contain shadow-2xl"
                }
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function ProviderTable({ head, rows }) {
  return (
    <div className="max-h-80 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-[#0c1230]/80 backdrop-blur">
          <tr className="text-left text-xs uppercase tracking-wider text-muted">
            {head.map((h) => <th key={h} className="py-1.5 pr-3 font-semibold">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className="border-b border-white/5">
              {cells.map((c, j) => (
                <td key={j} className={`py-1.5 pr-3 ${j === cells.length - 1 ? "font-semibold tabular-nums text-ink" : "text-muted"}`}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stars({ n }) {
  return (
    <span className="inline-flex items-center gap-0.5 text-amber-300">
      {Array.from({ length: n }).map((_, i) => <Star key={i} className="size-3 fill-current" />)}
    </span>
  );
}

function Badge({ tone, icon: Icon, children }) {
  const tones = {
    best: "border-emerald-400/30 bg-emerald-500/15 text-emerald-200",
    info: "border-brand/30 bg-brand/15 text-brand-soft",
    muted: "border-white/10 bg-white/[0.04] text-muted",
  };
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold ${tones[tone]}`}>
      <Icon className="size-3.5" /> {children}
    </span>
  );
}

function CenterCard({ icon: Icon, text, spin = false, tone, back = false }) {
  return (
    <div className="mx-auto max-w-2xl">
      <GlassCard className="p-10">
        <div className={`flex flex-col items-center gap-3 text-center ${tone === "err" ? "text-rose-300" : "text-muted"}`}>
          <Icon className={`size-8 ${spin ? "animate-spin" : ""}`} />
          <p className="text-sm">{text}</p>
          {back && (
            <a href="#/" className="mt-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-ink hover:bg-white/[0.07]">
              ← На поиск
            </a>
          )}
        </div>
      </GlassCard>
    </div>
  );
}
