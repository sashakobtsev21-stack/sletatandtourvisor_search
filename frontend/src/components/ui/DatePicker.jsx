import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * DatePicker — кастомный календарь в тёмном стеклянном стиле сайта.
 *
 * Нативный <input type="date"> рисует ОС-пикер (его нельзя стилизовать), поэтому
 * заменяем его собственным поповером: триггер-кнопка + анимированный календарь в
 * портале на body (тот же приём, что у Select — чтобы не «запираться» в stacking
 * context соседних motion-полей).
 *
 * Совместим по API с прежним <Input type="date">:
 *  - value (ISO "yyyy-mm-dd"), min, max — те же пропсы;
 *  - onChange получает событие вида { target: { value } };
 *  - name → скрытый input для отправки формы (FormData.get(name)).
 */

const MONTHS_NOM = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const MONTHS_SHORT = [
  "янв", "фев", "мар", "апр", "мая", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

// Анимация смены месяца: новый месяц въезжает со стороны направления листания.
const slideVariants = {
  enter: (d) => ({ opacity: 0, x: d > 0 ? 28 : -28 }),
  center: { opacity: 1, x: 0 },
  exit: (d) => ({ opacity: 0, x: d > 0 ? -28 : 28 }),
};

const pad = (n) => String(n).padStart(2, "0");
const toISO = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`; // m: 0-based
const todayISO = new Date().toISOString().slice(0, 10);

const controlBase =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] text-ink " +
  "text-sm outline-none transition-all duration-200 " +
  "focus:border-brand/60 focus:bg-white/[0.07] focus:ring-4 focus:ring-brand/20 " +
  "hover:border-white/20";

/** Подпись для триггера: «5 июн 2026». */
function formatLabel(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS_SHORT[m - 1]} ${y}`;
}

export function DatePicker({ id, name, value, min, max, onChange, icon = false, className = "" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const [view, setView] = useState(() => firstOfMonth(value || min || todayISO));
  const [dir, setDir] = useState(0); // направление смены месяца (для анимации)
  const ref = useRef(null);
  const popRef = useRef(null);

  // Открываем календарь на месяце выбранной даты.
  useEffect(() => {
    if (open) setView(firstOfMonth(value || min || todayISO));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const reposition = () => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const width = 296;
    // не вылезаем за правый край вьюпорта
    const left = Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - width - 12);
    setPos({ top: r.bottom + window.scrollY + 6, left: Math.max(window.scrollX + 8, left), width });
  };

  useLayoutEffect(() => {
    if (open) reposition();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current?.contains(e.target) || popRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    const onReflow = () => reposition();
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (iso) => {
    setOpen(false);
    onChange?.({ target: { value: iso } });
  };

  // Можно ли уйти на пред./след. месяц (не за пределы min/max).
  const prevDisabled = min ? toISO(view.y, view.m, 1) <= firstISO(min) : false;
  const nextDisabled = max ? toISO(view.y, view.m + 1, 1) > lastISO(max) : false;

  const step = (delta) => {
    setDir(delta);
    setView((v) => {
      const d = new Date(v.y, v.m + delta, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });
  };

  const cells = buildCells(view.y, view.m);

  return (
    <div className="relative" ref={ref}>
      {name && <input type="hidden" name={name} value={value || ""} readOnly />}
      <button
        id={id}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={[
          controlBase, "flex items-center justify-between py-2.5",
          icon ? "pl-9 pr-3" : "px-3",
          value ? "text-ink" : "text-muted/70", className,
        ].join(" ")}
      >
        <span className="truncate text-left">{value ? formatLabel(value) : "выбрать дату"}</span>
        <svg className={`ml-2 size-4 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
             viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && pos &&
        createPortal(
          <motion.div
            ref={popRef}
            role="dialog"
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            style={{ position: "absolute", top: pos.top, left: pos.left, width: pos.width }}
            className="z-[60] select-none rounded-2xl border border-white/10 bg-[#0b1026] p-3
                       shadow-[0_24px_60px_-12px_rgba(0,0,0,0.9)] ring-1 ring-black/40
                       bg-gradient-to-b from-white/[0.04] to-transparent"
          >
            {/* Шапка: месяц/год + навигация */}
            <div className="mb-2 flex items-center justify-between px-1">
              <NavBtn disabled={prevDisabled} onClick={() => step(-1)} aria-label="Предыдущий месяц">
                <ChevronLeft className="size-4" />
              </NavBtn>
              <div className="text-sm font-bold text-white">
                {MONTHS_NOM[view.m]} <span className="text-muted">{view.y}</span>
              </div>
              <NavBtn disabled={nextDisabled} onClick={() => step(1)} aria-label="Следующий месяц">
                <ChevronRight className="size-4" />
              </NavBtn>
            </div>

            {/* Дни недели */}
            <div className="mb-1 grid grid-cols-7 gap-1 px-0.5">
              {WEEKDAYS.map((w, i) => (
                <div key={w} className={`py-1 text-center text-[10px] font-semibold ${i >= 5 ? "text-rose-300/70" : "text-muted/70"}`}>
                  {w}
                </div>
              ))}
            </div>

            {/* Сетка дней с анимацией смены месяца */}
            <div className="relative overflow-hidden">
              <AnimatePresence initial={false} mode="popLayout" custom={dir}>
                <motion.div
                  key={`${view.y}-${view.m}`}
                  custom={dir}
                  variants={slideVariants}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="grid grid-cols-7 gap-1 px-0.5"
                >
                  {cells.map((cell, i) => {
                    if (cell == null) return <div key={`e${i}`} />;
                    const iso = toISO(view.y, view.m, cell);
                    const disabled = (min && iso < firstISO(min)) || (max && iso > lastISO(max));
                    const selected = iso === value;
                    const isToday = iso === todayISO;
                    const weekend = (i % 7) >= 5;
                    return (
                      <button
                        key={iso}
                        type="button"
                        disabled={disabled}
                        onClick={() => choose(iso)}
                        className={[
                          "relative grid h-9 place-items-center rounded-lg text-sm font-medium transition-colors",
                          disabled
                            ? "cursor-not-allowed text-muted/25"
                            : selected
                              ? "bg-gradient-to-br from-brand to-brand-deep text-white shadow-glow"
                              : weekend
                                ? "text-rose-200/90 hover:bg-white/10"
                                : "text-ink hover:bg-white/10",
                        ].join(" ")}
                      >
                        {cell}
                        {isToday && !selected && (
                          <span className="absolute bottom-1 size-1 rounded-full bg-ocean" />
                        )}
                      </button>
                    );
                  })}
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Быстрый переход «Сегодня/ближайшая доступная» */}
            <div className="mt-2 flex justify-between px-1 pt-1">
              <button
                type="button"
                onClick={() => {
                  const earliest = min && todayISO < firstISO(min) ? firstISO(min) : todayISO;
                  setView(firstOfMonth(earliest));
                }}
                className="rounded-lg px-2 py-1 text-[11px] font-semibold text-muted transition-colors hover:bg-white/10 hover:text-ink"
              >
                К ближайшей дате
              </button>
              {value && (
                <span className="rounded-lg px-2 py-1 text-[11px] font-semibold text-brand-soft">
                  {formatLabel(value)}
                </span>
              )}
            </div>
          </motion.div>,
          document.body
        )}
    </div>
  );
}

/** Кнопка навигации по месяцам. */
function NavBtn({ disabled, onClick, children, ...rest }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        "grid size-7 place-items-center rounded-lg border border-white/10 transition-colors",
        disabled ? "cursor-not-allowed text-muted/25" : "text-muted hover:border-brand/40 hover:bg-white/10 hover:text-ink",
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}

// --- helpers -----------------------------------------------------------------

function firstOfMonth(iso) {
  const [y, m] = (iso || todayISO).split("-").map(Number);
  return { y, m: m - 1 };
}

/** Сетка месяца, неделя с понедельника: ведущие null + числа 1..N. */
function buildCells(y, m) {
  const firstDow = new Date(y, m, 1).getDay();      // 0=Вс..6=Сб
  const offset = (firstDow + 6) % 7;                 // сдвиг до понедельника
  const days = new Date(y, m + 1, 0).getDate();
  const cells = Array(offset).fill(null);
  for (let d = 1; d <= days; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

// min/max могут приходить как ISO — работаем с первыми 10 символами.
const firstISO = (s) => String(s).slice(0, 10);
const lastISO = (s) => String(s).slice(0, 10);
