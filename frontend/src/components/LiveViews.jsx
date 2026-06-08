import { memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Radio, MonitorPlay, Loader2, CheckCircle2 } from "lucide-react";
import GlassCard from "./ui/GlassCard.jsx";
import { staggerContainer, fadeUp, slideIn } from "../lib/animations.js";
import { providerLabel } from "../lib/format.js";

/**
 * LiveViews — левая колонка: «живые» окна площадок (скриншоты в реальном времени).
 *
 * props:
 *  - providers: ["sletat", "tourvisor"] — какие окна показывать
 *  - frames:    { [provider]: base64jpeg } — последний кадр (реальный бэкенд)
 *  - phases:    { [provider]: "waiting"|"loading"|"done" } — фаза для демо без кадров
 *  - active:    bool — идёт ли поиск (показывать колонку или плейсхолдер)
 *
 * Если кадр пришёл — показываем картинку. Иначе рисуем состояние по фазе,
 * чтобы окно «жило» и не висело вечно на «ожидании».
 */
function LiveViewsImpl({ providers = [], frames = {}, phases = {}, active = false }) {
  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="flex h-full flex-col gap-4"
    >
      {!active ? (
        <GlassCard variants={slideIn("left")} className="p-6">
          <div className="flex flex-col items-center gap-3 py-10 text-center text-muted">
            <MonitorPlay className="size-8 opacity-40" />
            <p className="text-sm">
              Здесь в реальном времени появятся окна площадок,<br />как только запустится поиск.
            </p>
          </div>
        </GlassCard>
      ) : (
        <AnimatePresence>
          {providers.map((p) => {
            const phase = frames[p] ? "frame" : phases[p] ?? "waiting";
            const done = phase === "done";
            return (
              <GlassCard
                key={p}
                variants={fadeUp}
                layout
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -16 }}
                className="flex min-h-0 flex-1 flex-col overflow-hidden"
              >
                {/* Шапка окна: индикатор статуса меняется по фазе */}
                <div className="flex shrink-0 items-center gap-2 border-b border-white/10 bg-white/[0.03] px-4 py-2.5">
                  {done ? (
                    <span className="size-2.5 rounded-full bg-emerald-400 shadow-[0_0_10px_2px_rgba(52,211,153,0.6)]" />
                  ) : (
                    <span className="relative flex size-2.5">
                      <span className="absolute inline-flex size-full animate-ping rounded-full bg-rose-500/60" />
                      <span className="relative inline-flex size-2.5 rounded-full bg-rose-500" />
                    </span>
                  )}
                  <Radio className={`size-4 ${done ? "text-emerald-300" : "text-rose-300"}`} />
                  <span className="text-sm font-semibold capitalize text-ink">{providerLabel(p)}</span>
                  <span
                    className={`ml-auto text-[10px] font-medium uppercase tracking-wider ${
                      done ? "text-emerald-300/80" : "text-rose-300/80"
                    }`}
                  >
                    {done ? "снимок" : "live"}
                  </span>
                </div>

                {/* Тело: кадр или состояние по фазе. Кадр заполняет окно целиком
                    (object-cover + привязка к верху, где форма площадки) — без
                    тёмных полей по бокам и крупнее/читабельнее. */}
                <div className="relative min-h-0 flex-1 overflow-hidden bg-[#070b1c]/60">
                  {/* Рендерим РОВНО одну фазу. Без AnimatePresence: React сам
                      размонтирует предыдущее состояние, поэтому окно не может
                      «застрять» сразу в двух состояниях. Плавность даёт initial→animate. */}
                  {phase === "frame" && (
                    <motion.img
                      initial={{ opacity: 0, scale: 1.02 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.3 }}
                      src={`data:image/jpeg;base64,${frames[p]}`}
                      alt={`${p} live`}
                      className="absolute inset-0 size-full object-cover object-top"
                    />
                  )}
                  {phase === "waiting" && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-muted"
                    >
                      <Loader2 className="size-4 animate-spin" />
                      ожидание первого кадра…
                    </motion.div>
                  )}
                  {phase === "loading" && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="absolute inset-0 p-3"
                    >
                      <MockSnapshot loading />
                    </motion.div>
                  )}
                  {phase === "done" && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.35 }}
                      className="absolute inset-0 p-3"
                    >
                      <MockSnapshot />
                      <span className="absolute bottom-3 right-3 flex items-center gap-1 rounded-full bg-emerald-500/20 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                        <CheckCircle2 className="size-3.5" /> страница загружена
                      </span>
                    </motion.div>
                  )}
                </div>
              </GlassCard>
            );
          })}
        </AnimatePresence>
      )}
    </motion.div>
  );
}

/**
 * MockSnapshot — стилизованная «загруженная страница площадки»: шапка-браузер
 * и ряды результатов-скелетонов. В режиме loading блоки переливаются (shimmer),
 * в done — статичны. Это заглушка вместо реального скриншота, чтобы окно
 * выглядело живым в демо.
 */
function MockSnapshot({ loading = false }) {
  const block = `rounded-md ${
    loading
      ? "animate-shimmer bg-[length:200%_100%] bg-gradient-to-r from-white/[0.04] via-white/[0.12] to-white/[0.04]"
      : "bg-white/[0.06]"
  }`;
  return (
    <div className="flex h-full flex-col gap-2 rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
      {/* строка-браузер */}
      <div className="flex items-center gap-1.5">
        <span className="size-2 rounded-full bg-rose-400/70" />
        <span className="size-2 rounded-full bg-amber-400/70" />
        <span className="size-2 rounded-full bg-emerald-400/70" />
        <div className={`ml-2 h-3 flex-1 ${block}`} />
      </div>
      {/* ряды «результатов тура» */}
      <div className="flex flex-1 flex-col gap-2 overflow-hidden">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-2.5">
            <div className={`size-10 shrink-0 ${block}`} />
            <div className="flex flex-1 flex-col gap-1.5">
              <div className={`h-2.5 w-3/4 ${block}`} />
              <div className={`h-2 w-1/2 ${block}`} />
            </div>
            <div className={`h-5 w-14 shrink-0 ${block}`} />
          </div>
        ))}
      </div>
    </div>
  );
}

// React.memo (P3-a): кадры приходят каждые ~1.4с — без memo родитель пересчитывал
// поддерево и при изменениях phases/active мы ре-рендерились вхолостую.
const LiveViews = memo(LiveViewsImpl);
export default LiveViews;
