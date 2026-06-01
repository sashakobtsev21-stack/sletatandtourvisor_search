import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plane, Globe2, CalendarDays, MoonStar, Users, Baby,
  Wallet, Building2, Search, ChevronRight, Hotel, Sparkles,
  ShieldCheck, ChevronDown,
} from "lucide-react";
import GlassCard from "./ui/GlassCard.jsx";
import { Field, Input, Select } from "./ui/Field.jsx";
import { DatePicker } from "./ui/DatePicker.jsx";
import { staggerContainer, fadeUp, spring } from "../lib/animations.js";
import {
  DEPARTURE_CITIES, COUNTRIES, OPERATORS, PROVIDERS,
  NIGHTS, ADULTS, CHILDREN, CHILD_AGES, MAX_DATE_SPAN_DAYS,
} from "../lib/constants.js";

const addDays = (iso, n) => {
  const d = new Date(iso);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const today = new Date().toISOString().slice(0, 10);
// Минимально доступная дата — ЗАВТРА (сегодня выбирать нельзя).
const minDate = addDays(today, 1);
// Дефолтное окно: завтра … +7 дней.
const defaultFrom = minDate;
const defaultTo = addDays(minDate, 7);

/**
 * SearchForm — центральная колонка. Форма параметров поиска тура.
 * Анимации:
 *  - ступенчатое появление всех полей (staggerContainer + fadeUp на каждом Field);
 *  - микроинтеракции на чипах/кнопке (whileHover / whileTap);
 *  - плавное раскрытие зависимых блоков (возраст детей, фильтры рейсов) через AnimatePresence.
 *
 * props.onSubmit(payload) — вызывается с собранными параметрами при сабмите.
 * props.isSearching — блокирует кнопку, пока идёт поиск.
 * props.initial — параметры для предзаполнения (повтор прогона из истории).
 */
export default function SearchForm({ onSubmit, isSearching = false, initial = null }) {
  const [mode, setMode] = useState(initial?.search_mode ?? "tours"); // tours | hotels
  const [childrenCount, setChildrenCount] = useState(initial?.children_ages?.length ?? 0);
  const [childAges, setChildAges] = useState(initial?.children_ages ?? []);
  const [providers, setProviders] = useState(
    initial?.providers?.length ? [...initial.providers] : [...PROVIDERS]
  );
  const [operators, setOperators] = useState(initial?.operators ?? []);
  const [dateFrom, setDateFrom] = useState(initial?.date_from ?? defaultFrom);
  const [dateTo, setDateTo] = useState(initial?.date_to ?? defaultTo);
  const [nightsMin, setNightsMin] = useState(initial?.nights_min ?? 7);
  const [nightsMax, setNightsMax] = useState(initial?.nights_max ?? 10);

  // Ночи: «от» не больше «до» — при изменении одного подтягиваем второй.
  const onNightsMin = (v) => {
    const n = Number(v);
    setNightsMin(n);
    if (n > nightsMax) setNightsMax(n);
  };
  const onNightsMax = (v) => {
    const n = Number(v);
    setNightsMax(n);
    if (n < nightsMin) setNightsMin(n);
  };

  const isHotels = mode === "hotels";
  // Выезд: в отелях ≥ заезд+1 (ночи = выезд − заезд), в турах ≥ заезд; и не
  // дальше заезд + лимит окна. Это границы для пикера.
  const dateToMin = isHotels ? addDays(dateFrom, 1) : dateFrom;
  const dateToMax = addDays(dateFrom, MAX_DATE_SPAN_DAYS);

  // Зажать дату «до» в допустимый диапазон относительно «от».
  const clampTo = (from, to, hotels) => {
    const lo = hotels ? addDays(from, 1) : from;
    const hi = addDays(from, MAX_DATE_SPAN_DAYS);
    if (!to || to < lo) return lo;
    if (to > hi) return hi;
    return to;
  };
  const onFromChange = (v) => {
    const nf = v && v >= minDate ? v : minDate; // не раньше завтра
    setDateFrom(nf);
    setDateTo((prev) => clampTo(nf, prev, isHotels)); // «до» подстраивается под «от»
  };
  const onToChange = (v) => setDateTo(clampTo(dateFrom, v, isHotels));

  // При переключении Туры↔Отели подправить «до» (в отелях выезд ≥ заезд+1).
  useEffect(() => {
    setDateTo((prev) => clampTo(dateFrom, prev, isHotels));
  }, [isHotels]); // eslint-disable-line react-hooks/exhaustive-deps

  // Перестроить набор возрастов при изменении количества детей.
  const handleChildrenCount = (n) => {
    setChildrenCount(n);
    setChildAges((prev) => Array.from({ length: n }, (_, i) => prev[i] ?? 7));
  };

  const toggleProvider = (p) =>
    setProviders((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  const toggleOperator = (op) =>
    setOperators((prev) => (prev.includes(op) ? prev.filter((x) => x !== op) : [...prev, op]));

  const handleSubmit = (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    onSubmit?.({
      mode,
      departure_city: data.get("departure_city"),
      destination_country: data.get("destination_country"),
      date_from: data.get("date_from"),
      date_to: data.get("date_to"),
      // В отелях контрола ночей нет (ночи = даты проживания) — шлём валидные
      // значения по умолчанию, площадка всё равно выводит ночи из дат.
      nights_min: Number(data.get("nights_min")) || 7,
      nights_max: Number(data.get("nights_max")) || 10,
      adults: Number(data.get("adults")),
      child_ages: childAges,
      price_max: data.get("price_max") || null,
      operators,
      charter_only: data.get("charter_only") === "on",
      direct_only: data.get("direct_only") === "on",
      providers,
    });
  };

  return (
    <GlassCard
      as={motion.form}
      overflow="visible"
      onSubmit={handleSubmit}
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="p-6 md:p-7"
    >
      {/* Заголовок */}
      <motion.div variants={fadeUp} className="mb-5 flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-brand-deep shadow-glow">
          <Sparkles className="size-5 text-white" />
        </span>
        <div>
          <h2 className="text-xl font-extrabold tracking-tight text-white">Параметры поиска</h2>
          <p className="text-xs text-muted">Сравним {PROVIDERS.length} площадки за один прогон</p>
        </div>
      </motion.div>

      {/* Режим: Туры / Отели — сегментированный переключатель с «пилюлей» */}
      <motion.div variants={fadeUp} className="mb-5">
        <div className="relative grid grid-cols-2 gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1">
          {[
            { id: "tours", label: "Туры", icon: Plane },
            { id: "hotels", label: "Отели", icon: Hotel },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              className="relative z-10 flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-semibold transition-colors"
            >
              {mode === id && (
                <motion.span
                  layoutId="mode-pill"
                  transition={spring}
                  className="absolute inset-0 -z-10 rounded-lg bg-gradient-to-r from-brand to-brand-deep shadow-glow"
                />
              )}
              <Icon className={`size-4 ${mode === id ? "text-white" : "text-muted"}`} />
              <span className={mode === id ? "text-white" : "text-muted"}>{label}</span>
            </button>
          ))}
        </div>
      </motion.div>

      {/* Откуда (только туры) + Куда.
          ВАЖНО: тут только обычный условный рендер, без motion-обёрток с
          initial:opacity:0 / height:0 — при переключении Туры↔Отели они застревали
          в скрытом состоянии (поле в DOM, но невидимо). Field сам даёт появление. */}
      <div className="grid gap-4 sm:grid-cols-2">
        {!isHotels && (
          <Field label="Откуда?" icon={Plane} htmlFor="departure_city">
            <Select id="departure_city" name="departure_city" icon searchable defaultValue={initial?.departure_city ?? "Москва"}>
              {DEPARTURE_CITIES.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </Field>
        )}

        <Field label="Куда?" icon={Globe2} htmlFor="destination_country">
          <Select id="destination_country" name="destination_country" icon searchable defaultValue={initial?.destination_country ?? "Турция"}>
            {COUNTRIES.map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
      </div>

      {/* Даты. В отелях это даты проживания (заезд→выезд) — ими же задаются ночи. */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label={isHotels ? "Заезд" : "Дата вылета (от)"} icon={CalendarDays} htmlFor="date_from">
          <DatePicker
            id="date_from" name="date_from" icon min={minDate} value={dateFrom}
            onChange={(e) => onFromChange(e.target.value)}
          />
        </Field>
        <Field label={isHotels ? "Выезд" : "Дата вылета (до)"} icon={CalendarDays} htmlFor="date_to">
          <DatePicker
            id="date_to" name="date_to" icon min={dateToMin} max={dateToMax} value={dateTo}
            onChange={(e) => onToChange(e.target.value)}
          />
        </Field>
      </div>
      <motion.p variants={fadeUp} className="mt-1.5 text-[11px] text-muted">
        {isHotels
          ? `Ночи задаются датами проживания: выезд − заезд (не более ${MAX_DATE_SPAN_DAYS} ночей).`
          : `Диапазон дат вылета — не более ${MAX_DATE_SPAN_DAYS} дней.`}
      </motion.p>

      {/* Ночи — только для туров. В отелях ночи = диапазон дат проживания (контрола нет). */}
      {!isHotels && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Ночей от" icon={MoonStar} htmlFor="nights_min">
            <Select id="nights_min" name="nights_min" icon value={nightsMin} onChange={(e) => onNightsMin(e.target.value)}>
              {NIGHTS.map((n) => <option key={n}>{n}</option>)}
            </Select>
          </Field>
          <Field label="Ночей до" icon={MoonStar} htmlFor="nights_max">
            <Select id="nights_max" name="nights_max" icon value={nightsMax} onChange={(e) => onNightsMax(e.target.value)}>
              {NIGHTS.map((n) => <option key={n}>{n}</option>)}
            </Select>
          </Field>
        </div>
      )}

      {/* Туристы + бюджет */}
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Field label="Взрослых" icon={Users} htmlFor="adults">
          <Select id="adults" name="adults" icon defaultValue={initial?.adults ?? 2}>
            {ADULTS.map((a) => <option key={a}>{a}</option>)}
          </Select>
        </Field>
        <Field label="Детей" icon={Baby} htmlFor="childrenCount">
          <Select
            id="childrenCount"
            icon
            value={childrenCount}
            onChange={(e) => handleChildrenCount(Number(e.target.value))}
          >
            {CHILDREN.map((k) => <option key={k}>{k}</option>)}
          </Select>
        </Field>
        <Field label="Макс. цена, ₽" icon={Wallet} htmlFor="price_max">
          <Input id="price_max" name="price_max" type="text" icon placeholder="любая" inputMode="numeric" defaultValue={initial?.price_max ?? ""} />
        </Field>
      </div>

      {/* Возраст детей — по количеству. Обычный условный рендер (без height-анимации,
          которая оставляла селекты невидимыми, но кликабельными). */}
      {childrenCount > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {childAges.map((age, i) => (
            <Field key={i} label={`Возраст ребёнка ${i + 1}`} icon={Baby}>
              <Select
                icon
                value={age}
                onChange={(e) =>
                  setChildAges((prev) =>
                    prev.map((v, idx) => (idx === i ? Number(e.target.value) : v))
                  )
                }
              >
                {CHILD_AGES.map((a) => <option key={a} value={a}>{a}</option>)}
              </Select>
            </Field>
          ))}
        </div>
      )}

      {/* Туроператоры — мультивыбор чипами */}
      <motion.div variants={fadeUp} className="mt-5">
        <label className="mb-2 block text-xs font-medium tracking-wide text-muted">
          Туроператоры{" "}
          <span className="text-muted/60">
            {operators.length ? `выбрано: ${operators.length}` : "(пусто = все)"}
          </span>
        </label>
        <div className="flex max-h-44 flex-wrap gap-2 overflow-y-auto rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
          {OPERATORS.map((op) => {
            const active = operators.includes(op);
            return (
              <motion.button
                key={op}
                type="button"
                onClick={() => toggleOperator(op)}
                whileHover={{ scale: 1.05, y: -1 }}
                whileTap={{ scale: 0.95 }}
                className={[
                  "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                  active
                    ? "border-brand/50 bg-brand/20 text-white shadow-glow"
                    : "border-white/10 bg-white/[0.03] text-muted hover:text-ink",
                ].join(" ")}
              >
                <Building2 className="size-3.5" />
                {op}
              </motion.button>
            );
          })}
        </div>
      </motion.div>

      {/* Фильтры рейсов — только для туров */}
      {!isHotels && (
        <div className="mt-5">
          <label className="mb-2 block text-xs font-medium tracking-wide text-muted">Рейсы</label>
          <div className="flex flex-wrap gap-5">
            <Checkbox name="charter_only" label="Только чартер" defaultChecked={!!initial?.charter_only} />
            <Checkbox name="direct_only" label="Только прямые" defaultChecked={!!initial?.direct_only} />
          </div>
        </div>
      )}

      {/* Площадки для сравнения */}
      <motion.div variants={fadeUp} className="mt-5">
        <label className="mb-2 block text-xs font-medium tracking-wide text-muted">
          Площадки для сравнения
        </label>
        <div className="flex flex-wrap gap-2">
          {PROVIDERS.map((p) => {
            const active = providers.includes(p);
            return (
              <motion.button
                key={p}
                type="button"
                onClick={() => toggleProvider(p)}
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.96 }}
                className={[
                  "flex items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-semibold capitalize transition-colors",
                  active
                    ? "border-ocean/40 bg-ocean/15 text-white"
                    : "border-white/10 bg-white/[0.03] text-muted hover:text-ink",
                ].join(" ")}
              >
                <span
                  className={`size-2 rounded-full ${active ? "bg-ocean shadow-[0_0_10px_2px_rgba(56,224,216,0.6)]" : "bg-muted/40"}`}
                />
                {p}
              </motion.button>
            );
          })}
        </div>
      </motion.div>

      {/* Кнопка сабмита — крупная, с микроинтеракцией и состоянием загрузки */}
      <motion.button
        variants={fadeUp}
        type="submit"
        disabled={isSearching || providers.length === 0}
        whileHover={{ scale: isSearching ? 1 : 1.02 }}
        whileTap={{ scale: isSearching ? 1 : 0.98 }}
        className={[
          "group relative mt-6 flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl",
          "bg-gradient-to-r from-brand-deep via-brand to-ocean py-3.5 text-base font-bold text-white",
          "shadow-glow transition-opacity disabled:opacity-50",
        ].join(" ")}
      >
        {/* бегущий блик при наведении */}
        <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
        {isSearching ? (
          <>
            <span className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            Идёт поиск…
          </>
        ) : (
          <>
            <Search className="size-5" />
            Сравнить
            <ChevronRight className="size-4 transition-transform group-hover:translate-x-1" />
          </>
        )}
      </motion.button>

      <HealthCheckInfo providers={providers} />
    </GlassCard>
  );
}

/**
 * HealthCheckInfo — раскрывающийся блок: коротко о том, что делает health-check.
 * Проверяются ТОЛЬКО выбранные площадки (в коде run_health_check(providers=chosen)).
 */
function HealthCheckInfo({ providers = [] }) {
  const [open, setOpen] = useState(false);

  return (
    <motion.div variants={fadeUp} className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-center gap-1.5 text-[11px] text-muted transition-colors hover:text-ink"
      >
        <ShieldCheck className="size-3.5 text-ocean" />
        Перед прогоном выполняется health-check каждой площадки
        <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-2 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs text-muted">
              <p>
                Health-check открывает форму площадки и убеждается, что ключевые элементы
                на месте. Если структура сайта изменилась — прогон блокируется, чтобы не
                искать «вслепую».
              </p>
              <p>
                Проверяются <b className="text-ink">только выбранные</b> площадки
                {providers.length
                  ? <>: <span className="capitalize text-ink">{providers.join(", ")}</span>.</>
                  : " (отметь площадки ниже)."}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/** Кастомный чекбокс в фирменном стиле. */
function Checkbox({ name, label, defaultChecked = false }) {
  const [checked, setChecked] = useState(defaultChecked);
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink">
      <input type="checkbox" name={name} defaultChecked={defaultChecked} className="peer sr-only" onChange={(e) => setChecked(e.target.checked)} />
      <motion.span
        whileTap={{ scale: 0.85 }}
        className={[
          "grid size-5 place-items-center rounded-md border transition-colors",
          checked ? "border-brand bg-brand" : "border-white/20 bg-white/[0.04]",
        ].join(" ")}
      >
        <AnimatePresence>
          {checked && (
            <motion.svg
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0, opacity: 0 }}
              className="size-3.5 text-white" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="3"
            >
              <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
            </motion.svg>
          )}
        </AnimatePresence>
      </motion.span>
      {label}
    </label>
  );
}
