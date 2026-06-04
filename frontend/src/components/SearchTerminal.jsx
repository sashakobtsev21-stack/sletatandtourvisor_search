import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Terminal, CircleStop, CheckCircle2, AlertTriangle, Info, Loader2 } from "lucide-react";
import GlassCard from "./ui/GlassCard.jsx";
import { fadeUp, logLine } from "../lib/animations.js";

// Цвет/иконка строки лога по уровню. Уровни совпадают с SSE-потоком бэкенда:
// log(level=INFO|WARNING), ok, err.
const LEVELS = {
  info: { color: "text-sky-200", icon: Info },
  ok: { color: "text-emerald-300", icon: CheckCircle2 },
  warning: { color: "text-amber-300", icon: AlertTriangle },
  err: { color: "text-rose-300", icon: AlertTriangle },
};

/**
 * SearchTerminal — правая колонка: прогресс-бар + технологичный терминал логов.
 *
 * props:
 *  - logs: [{ id, level, msg, ts }]  — поступающие строки (append-only)
 *  - progress: 0..100
 *  - status: "idle" | "running" | "done" | "error" | "cancelled"
 *  - onCancel(): обработчик кнопки «Остановить»
 */
export default function SearchTerminal({ logs = [], progress = 0, status = "idle", onCancel }) {
  const scrollRef = useRef(null);

  // Плавный автоскролл вниз при каждом новом сообщении.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [logs.length]);

  const isRunning = status === "running";
  const clamped = Math.max(0, Math.min(100, progress)); // нескруглённое — для плавной ширины бара
  const pct = Math.round(clamped);

  return (
    <GlassCard variants={fadeUp} initial="hidden" animate="show" className="flex h-full flex-col p-5">
      {/* Шапка: статус + кнопка остановки + проценты */}
      <div className="mb-4 flex items-center gap-3">
        <span className="grid size-9 place-items-center rounded-lg bg-white/[0.06]">
          {isRunning ? (
            <Loader2 className="size-5 animate-spin text-brand-soft" />
          ) : (
            <Terminal className="size-5 text-brand-soft" />
          )}
        </span>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-white">Выполнение поиска</h3>
          <StatusBadge status={status} />
        </div>

        <AnimatePresence>
          {isRunning && (
            <motion.button
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={onCancel}
              className="flex items-center gap-1.5 rounded-lg border border-rose-400/30 bg-rose-500/15 px-3 py-1.5 text-xs font-semibold text-rose-200 transition-colors hover:bg-rose-500/25"
            >
              <CircleStop className="size-4" />
              Стоп
            </motion.button>
          )}
        </AnimatePresence>
      </div>

      {/* Прогресс-бар */}
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-muted">Прогресс</span>
        <motion.b
          key={pct}
          initial={{ scale: 1.3, color: "#a9adff" }}
          animate={{ scale: 1, color: "#e7ecff" }}
          className="tabular-nums font-bold"
        >
          {pct}%
        </motion.b>
      </div>
      <div className="relative mb-5 h-2.5 overflow-hidden rounded-full bg-white/[0.06]">
        <motion.span
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-brand-deep via-brand to-ocean"
          initial={{ width: 0 }}
          animate={{ width: `${clamped}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
        {/* бегущий блик поверх заполненной части, пока идёт поиск */}
        {isRunning && (
          <span
            className="absolute inset-y-0 left-0 animate-shimmer rounded-full bg-[length:200%_100%] bg-gradient-to-r from-transparent via-white/40 to-transparent"
            style={{ width: `${clamped}%` }}
          />
        )}
      </div>

      {/* Терминал логов */}
      <div
        ref={scrollRef}
        className="relative flex-1 overflow-y-auto rounded-xl bg-[#070b1c]/80 p-3 font-mono text-xs leading-relaxed shadow-inset-terminal"
      >
        {logs.length === 0 ? (
          <div className="flex h-full min-h-[200px] items-center justify-center text-center text-muted">
            <span>
              <Terminal className="mx-auto mb-2 size-6 opacity-40" />
              Лог появится здесь после запуска поиска…
            </span>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {logs.map((line) => {
              const meta = LEVELS[line.level] ?? LEVELS.info;
              const Icon = meta.icon;
              return (
                <motion.div
                  key={line.id}
                  variants={logLine}
                  initial="hidden"
                  animate="show"
                  exit="exit"
                  layout
                  className={`flex items-start gap-2 py-0.5 ${meta.color}`}
                >
                  {line.ts && <span className="shrink-0 text-muted/50">{line.ts}</span>}
                  <Icon className="mt-0.5 size-3.5 shrink-0 opacity-80" />
                  <span className="break-words">{line.msg}</span>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
        {/* мигающий курсор внизу, пока идёт поиск */}
        {isRunning && (
          <motion.span
            animate={{ opacity: [1, 0.2, 1] }}
            transition={{ repeat: Infinity, duration: 1 }}
            className="ml-5 inline-block h-3.5 w-2 translate-y-0.5 bg-brand-soft"
          />
        )}
      </div>
    </GlassCard>
  );
}

/** Бейдж статуса под заголовком терминала. */
function StatusBadge({ status }) {
  const map = {
    idle: ["Ожидание", "text-muted", "bg-white/10"],
    running: ["В процессе", "text-brand-soft", "bg-brand/20"],
    done: ["Готово", "text-emerald-300", "bg-emerald-500/15"],
    error: ["Ошибка", "text-rose-300", "bg-rose-500/15"],
    cancelled: ["Остановлено", "text-amber-300", "bg-amber-500/15"],
  };
  const [label, color, bg] = map[status] ?? map.idle;
  return (
    <span className={`mt-0.5 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold ${color} ${bg}`}>
      <span className={`size-1.5 rounded-full ${status === "running" ? "animate-pulseDot" : ""} bg-current`} />
      {label}
    </span>
  );
}
