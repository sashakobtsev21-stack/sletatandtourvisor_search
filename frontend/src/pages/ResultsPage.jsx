import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Hotel, Plane, ArrowLeft, ImageIcon, ExternalLink, AlertTriangle, Loader2, Star, Trophy, Info,
} from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { formatPrice, formatDate, providerLabel } from "../lib/format.js";
import { apiFetch } from "../lib/api.js";
import { takeResult } from "../lib/resultStore.js";

/**
 * ResultsPage — отчёт сравнения одного прогона (#/run/{id}).
 * Главное содержимое — по КАЖДОЙ площадке таблица «Туроператор / Наименьшая цена /
 * Скорость», ниже (в режиме «Отели») первые 10 отелей. Без дублирующей сводной
 * таблицы — сравнение читается из двух карточек рядом.
 */
export default function ResultsPage({ runId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [shot, setShot] = useState(null); // {src, cap} для модалки скриншота
  const [zoom, setZoom] = useState(false); // приближён ли скриншот

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    const stashed = takeResult(runId); // гость: отчёт уже у нас (минуя защищённый /api/runs)
    if (stashed) {
      setData(stashed);
      return () => { alive = false; };
    }
    apiFetch(`/api/runs/${runId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => alive && setData(j))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [runId]);

  // Закрытие модалки скриншота по Escape (клавиатурная доступность).
  useEffect(() => {
    if (!shot) return;
    const onKey = (e) => { if (e.key === "Escape") setShot(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shot]);

  if (error) return <CenterCard icon={AlertTriangle} tone="err" text={`Не удалось загрузить прогон #${runId}: ${error}`} back />;
  if (!data) return <CenterCard icon={Loader2} spin text={`Загружаю прогон #${runId}…`} />;

  const p = data.params;
  const hotels = p.search_mode === "hotels";

  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="mx-auto max-w-5xl space-y-5">
      {/* Шапка: маршрут + лучший вариант одной строкой */}
      <GlassCard variants={fadeUp} className="p-5">
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

        {data.best && (
          <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-500/15 px-3 py-1.5 text-sm font-semibold text-emerald-200">
            <Trophy className="size-4" /> Лучшее: {formatPrice(data.best.price)} — {data.best.label} · {hotels ? "отель" : "оператор"}, {providerLabel(data.best.provider)}
          </div>
        )}
      </GlassCard>

      {/* По каждой площадке: операторы (3 колонки) + первые 10 отелей */}
      <div className="grid gap-5 md:grid-cols-2">
        {data.results.map((r) => (
          <GlassCard key={r.provider} variants={fadeUp} className="p-5">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h3 className="text-base font-bold capitalize text-white">{providerLabel(r.provider)}</h3>
              {r.success && <span className="text-xs text-muted">{r.duration_seconds.toFixed(1)} с</span>}
              <div className="ml-auto flex items-center gap-3 text-xs">
                {r.screenshot_url && (
                  <button
                    type="button"
                    onClick={() => { setZoom(false); setShot({ src: r.screenshot_url, cap: `${providerLabel(r.provider)} — выдача` }); }}
                    className="flex items-center gap-1 text-ocean transition-colors hover:text-brand-soft"
                  >
                    <ImageIcon className="size-3.5" /> скриншот
                  </button>
                )}
                {r.search_url && (
                  <span className="flex items-center gap-1">
                    <a href={r.search_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-ocean transition-colors hover:text-brand-soft">
                      <ExternalLink className="size-3.5" /> поиск
                    </a>
                    {r.provider === "tourvisor" && hotels && (
                      <Info
                        className="size-3.5 cursor-help text-amber-300/80"
                        title="Ведёт на общий поиск Турвизора без сохранённых параметров — задайте их на сайте вручную."
                      />
                    )}
                  </span>
                )}
              </div>
            </div>

            {r.unsupported_filters?.length > 0 && (
              <p className="mb-2 flex items-start gap-1.5 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <Info className="size-3.5 shrink-0" />
                <span>
                  Площадка не поддерживает: <code>{r.unsupported_filters.join(", ")}</code>
                  — эти фильтры в выдаче <b>не применены</b>.
                </span>
              </p>
            )}
            {!r.success ? (
              r.not_applicable ? (
                <p className="flex items-start gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-muted">
                  <span className="shrink-0">ℹ️</span>
                  <span>{r.error}</span>
                </p>
              ) : (
                <p className="text-sm text-rose-300">⚠️ {r.error || "поиск не дал результатов"}</p>
              )
            ) : (
              <div className="space-y-4">
                <div>
                  <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
                    Туроператоры
                  </h4>
                  <OperatorTable offers={r.operator_offers} available={r.operators_available} />
                </div>

                {r.hotel_offers?.length > 0 && (
                  <div>
                    <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
                      Отели (первые 10)
                    </h4>
                    <ProviderTable
                      head={["Отель", "★", "Цена"]}
                      rows={r.hotel_offers.slice(0, 10).map((h) => [
                        h.hotel_name,
                        h.stars ? <Stars n={h.stars} /> : "—",
                        formatPrice(h.price, h.currency),
                      ])}
                    />
                  </div>
                )}

                <OperatorStatuses noTours={r.operators_no_tours} notResponding={r.operators_not_responding} />
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

function ProviderTable({ head, rows, emphasizeCol }) {
  const emph = emphasizeCol ?? head.length - 1; // какую колонку выделить (по умолчанию последнюю)
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
                <td key={j} className={`py-1.5 pr-3 ${j === emph ? "font-semibold tabular-nums text-ink" : "text-muted"}`}>{c}</td>
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

/**
 * OperatorTable — единый формат для всех площадок: «Туроператор / Наименьшая цена»
 * (2 колонки). Колонку «Скорость» убрали — её даёт только Sletat, из-за неё карточки
 * выглядели по-разному. Пусто (площадка не раскрывает операторов, напр. Level) —
 * нейтральная строка в том же месте, чтобы структура карточек совпадала.
 */
function OperatorTable({ offers = [], available = [] }) {
  if (!offers.length) {
    // Цены по операторам недоступны (Level шифрует), но известны имена ТО с турами.
    if (available.length)
      return (
        <div>
          <p className="mb-1.5 text-xs text-muted">Цены по операторам не раскрываются; туры есть у:</p>
          <div className="flex flex-wrap gap-1.5">
            {available.map((n) => (
              <span key={n} className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] text-ink">
                {n}
              </span>
            ))}
          </div>
        </div>
      );
    return <p className="text-sm text-muted">Разбивка по операторам недоступна.</p>;
  }
  const rows = offers.map((o) => [o.operator, formatPrice(o.price, o.currency)]);
  return <ProviderTable head={["Туроператор", "Наименьшая цена"]} emphasizeCol={1} rows={rows} />;
}

/** OperatorStatuses — операторы без туров и не ответившие (из блинчика Sletat). */
function OperatorStatuses({ noTours = [], notResponding = [] }) {
  if (!noTours.length && !notResponding.length) return null;
  const Group = ({ title, items, tone }) => (
    <div>
      <div className={`mb-1 text-[11px] font-semibold uppercase tracking-wider ${tone}`}>
        {title} · {items.length}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((n) => (
          <span key={n} className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[11px] text-muted">
            {n}
          </span>
        ))}
      </div>
    </div>
  );
  return (
    <div className="space-y-2 border-t border-white/5 pt-3">
      {noTours.length > 0 && <Group title="Туров нет" items={noTours} tone="text-muted" />}
      {notResponding.length > 0 && <Group title="Оператор не отвечает" items={notResponding} tone="text-amber-300/80" />}
    </div>
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
