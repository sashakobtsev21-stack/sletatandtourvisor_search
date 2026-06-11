import { memo, useEffect, useState } from "react";
import { m, AnimatePresence } from "framer-motion";
import {
  Plane, Globe2, CalendarDays, MoonStar, Users, Baby,
  Building2, Search, ChevronRight, Hotel, Sparkles,
  ShieldCheck, ChevronDown,
} from "lucide-react";
import GlassCard from "./ui/GlassCard.jsx";
import { Field, Select } from "./ui/Field.jsx";
import { DatePicker } from "./ui/DatePicker.jsx";
import { staggerContainer, fadeUp, spring } from "../lib/animations.js";
import {
  PROVIDERS, NIGHTS, ADULTS, CHILDREN, CHILD_AGES, MAX_DATE_SPAN_DAYS,
} from "../lib/constants.js";
import { useRefData } from "../lib/refdata.js";
import { providerLabel } from "../lib/format.js";
import { incompatReasons, caveatOf } from "../lib/providerCoverage.js";

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
 * SearchForm — центральная колонка. Форма параметров одиночного поиска тура.
 * Анимации:
 *  - ступенчатое появление всех полей (staggerContainer + fadeUp на каждом Field);
 *  - микроинтеракции на чипах/кнопке (whileHover / whileTap);
 *  - плавное раскрытие зависимых блоков (возраст детей, фильтры рейсов) через AnimatePresence.
 *
 * props.onSubmit(payload) — вызывается с собранными параметрами при сабмите.
 * props.isSearching — блокирует кнопку, пока идёт поиск.
 * props.initial — параметры для предзаполнения (повтор прогона из истории).
 *
 * Мультипоиск (много направлений) — отдельная страница BatchPage с собственной формой
 * (per-direction даты); раньше здесь был prop `batch`, теперь выпилен как мёртвый код.
 * Обёрнут в memo: во время поиска SearchPage тикает прогресс ~4 раза/сек, и без memo
 * этот тяжёлый компонент перерисовывался бы каждый тик.
 */
function SearchForm({ onSubmit, isSearching = false, initial = null }) {
  // Справочники с бэкенда (/api/refdata); до ответа — фолбэк-константы.
  const { departureCities, countries, operators: operatorOptions, providers: providerOptions,
          providerModes = {}, providerCoverage = {} } = useRefData();
  const [mode, setMode] = useState(initial?.search_mode ?? "tours"); // tours | hotels
  const [childrenCount, setChildrenCount] = useState(initial?.children_ages?.length ?? 0);
  const [childAges, setChildAges] = useState(initial?.children_ages ?? []);
  // Дефолт — все доступные площадки (audit-2026-06). Раньше брали лишь
  // `constants.PROVIDERS = ["sletat","tourvisor"]`, остальные приходилось включать руками.
  // Сейчас при первой подгрузке /api/refdata расширяем до полного refProv (см. useEffect ниже).
  const [providers, setProviders] = useState(
    initial?.providers?.length ? [...initial.providers] : [...PROVIDERS]
  );
  const [providersTouched, setProvidersTouched] = useState(!!initial?.providers?.length);
  const [operators, setOperators] = useState(initial?.operators ?? []);
  const [dateFrom, setDateFrom] = useState(initial?.date_from ?? defaultFrom);
  const [dateTo, setDateTo] = useState(initial?.date_to ?? defaultTo);
  const [nightsMin, setNightsMin] = useState(initial?.nights_min ?? 7);
  const [nightsMax, setNightsMax] = useState(initial?.nights_max ?? 10);
  const [departureCity, setDepartureCity] = useState(initial?.departure_city ?? "Москва"); // контролируемый — для сводки
  // controlled — иначе провайдерные подсказки про «нет страны X» не работали (audit-2026-06).
  const [destinationCountry, setDestinationCountry] = useState(initial?.destination_country ?? "Турция");
  const [adults, setAdults] = useState(initial?.adults ?? 2);

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

  // Режимы площадки (с бэкенда /api/refdata). Нет данных → считаем, что поддерживает оба.
  const providerSupportsMode = (p, m = mode) =>
    (providerModes[p] ?? ["tours", "hotels"]).includes(m);
  // Если площадка работает только в одном режиме — подпись для подсказки/бейджа.
  const providerOnlyMode = (p) => {
    const m = providerModes[p];
    if (!m || m.length !== 1) return null;
    return m[0] === "hotels" ? "Отели" : "Туры";
  };

  // При смене режима убираем выбранные площадки, несовместимые с новым режимом
  // (напр. Островок в «Турах»), И добавляем те, что становятся релевантными в
  // НОВОМ режиме (напр. Островок при переключении на «Отели» — audit-2026-06).
  // Добавляем все совместимые с новым mode площадки из refdata — пользователь
  // ожидает «по умолчанию сравнивать всё».
  useEffect(() => {
    setProviders((prev) => {
      const kept = prev.filter((p) => providerSupportsMode(p, mode));
      const newlyCompatible = (providerOptions || []).filter(
        (p) => providerSupportsMode(p, mode) && !kept.includes(p));
      return [...kept, ...newlyCompatible];
    });
  }, [mode, providerModes, providerOptions]); // eslint-disable-line react-hooks/exhaustive-deps

  // При первой подгрузке /api/refdata расширяем выбор до ВСЕХ совместимых площадок
  // (audit-2026-06: пользователь должен по умолчанию сравнивать всё, а не только sletat+tourvisor).
  // Делается один раз — после первого юзер-тача (providersTouched=true) больше не вмешиваемся.
  useEffect(() => {
    if (providersTouched || !providerOptions?.length) return;
    const compatible = providerOptions.filter((p) => providerSupportsMode(p, mode));
    if (compatible.length > providers.length) setProviders(compatible);
  }, [providerOptions, mode, providerModes]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleProvider = (p) => {
    if (!providerSupportsMode(p)) return; // несовместима с текущим режимом — не выбираем
    setProvidersTouched(true);
    setProviders((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  };

  const toggleOperator = (op) =>
    setOperators((prev) => (prev.includes(op) ? prev.filter((x) => x !== op) : [...prev, op]));

  const handleSubmit = (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const shared = {
      mode,
      departure_city: data.get("departure_city"),
      date_from: data.get("date_from"),
      date_to: data.get("date_to"),
      // В отелях контрола ночей нет (ночи = даты проживания) — шлём валидные
      // значения по умолчанию, площадка всё равно выводит ночи из дат.
      nights_min: Number(data.get("nights_min")) || 7,
      nights_max: Number(data.get("nights_max")) || 10,
      adults: Number(data.get("adults")),
      child_ages: childAges,
      operators,
      charter_only: data.get("charter_only") === "on",
      direct_only: data.get("direct_only") === "on",
      providers,
    };
    onSubmit?.({ ...shared, destination_country: destinationCountry });
  };

  return (
    <GlassCard
      as={m.form}
      overflow="visible"
      onSubmit={handleSubmit}
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="p-6 md:p-7"
    >
      {/* Заголовок */}
      <m.div variants={fadeUp} className="mb-5 flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-brand-deep shadow-glow">
          <Sparkles className="size-5 text-white" />
        </span>
        <div>
          <h2 className="text-xl font-extrabold tracking-tight text-white">
            {batch ? "Мультипоиск" : "Параметры поиска"}
          </h2>
          <p className="text-xs text-muted">
            {batch
              ? "Один набор параметров — сразу по многим направлениям"
              : `Сравним ${providerOptions.length} площадки за один прогон`}
          </p>
        </div>
      </m.div>

      {/* Режим: Туры / Отели — сегментированный переключатель с «пилюлей» */}
      <m.div variants={fadeUp} className="mb-5">
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
                <m.span
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
      </m.div>

      {/* Откуда (только туры) + Куда.
          ВАЖНО: тут только обычный условный рендер, без motion-обёрток с
          initial:opacity:0 / height:0 — при переключении Туры↔Отели они застревали
          в скрытом состоянии (поле в DOM, но невидимо). Field сам даёт появление. */}
      <div className="grid gap-4 sm:grid-cols-2">
        {!isHotels && (
          <Field label="Откуда?" icon={Plane} htmlFor="departure_city">
            <Select id="departure_city" name="departure_city" icon searchable value={departureCity} onChange={(e) => setDepartureCity(e.target.value)}>
              {departureCities.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </Field>
        )}

        <Field label="Куда?" icon={Globe2} htmlFor="destination_country">
          <Select id="destination_country" name="destination_country" icon searchable
                  value={destinationCountry}
                  onChange={(e) => setDestinationCountry(e.target.value)}>
            {countries.map((c) => <option key={c}>{c}</option>)}
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
      <m.p variants={fadeUp} className="mt-1.5 text-[11px] text-muted">
        {isHotels
          ? `Ночи задаются датами проживания: выезд − заезд (не более ${MAX_DATE_SPAN_DAYS} ночей).`
          : `Диапазон дат вылета — не более ${MAX_DATE_SPAN_DAYS} дней.`}
      </m.p>

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

      {/* Туристы */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Взрослых" icon={Users} htmlFor="adults">
          <Select id="adults" name="adults" icon value={adults} onChange={(e) => setAdults(Number(e.target.value))}>
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

      {/* Туроператоры — мультивыбор чипами. В режиме мультипоиска скрыто (одни параметры на все направления). */}
      {!batch && (
        <m.div variants={fadeUp} className="mt-5">
          <label className="mb-2 block text-xs font-medium tracking-wide text-muted">
            Туроператоры{" "}
            <span className="text-muted/60">
              {operators.length ? `выбрано: ${operators.length}` : "(пусто = все)"}
            </span>
          </label>
          <div className="flex max-h-44 flex-wrap gap-2 overflow-y-auto rounded-xl border border-white/5 bg-white/[0.02] p-2.5">
            {operatorOptions.map((op) => {
              const active = operators.includes(op);
              return (
                <m.button
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
                </m.button>
              );
            })}
          </div>
        </m.div>
      )}

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
      <m.div variants={fadeUp} className="mt-5">
        <label className="mb-2 block text-xs font-medium tracking-wide text-muted">
          Площадки для сравнения
        </label>
        <div className="flex flex-wrap gap-2">
          {providerOptions.map((p) => {
            const active = providers.includes(p);
            const incompatible = !providerSupportsMode(p); // не работает в текущем режиме
            const onlyMode = providerOnlyMode(p);          // "Туры"/"Отели" — для бейджа
            // Не-блокирующие предупреждения по покрытию: город/страна/режим/операторы
            // не поддерживаются площадкой. Площадка всё равно отметится (агрегаторы
            // Sletat/Tourvisor всегда поддерживают всё, остальные — ограничены).
            // UI подсвечивает + баннер ниже перечисляет.
            const reasons = incompatReasons(providerCoverage, p, {
              city: !isHotels ? departureCity : undefined,    // в отелях вылет не критичен
              country: batch ? undefined : destinationCountry,  // в батче страна per-direction
              mode,
              operators,
            });
            const partial = !incompatible && reasons.length > 0;   // частично поддерживает
            const caveat = caveatOf(providerCoverage, p);
            const tooltipParts = [];
            if (incompatible) tooltipParts.push(`Площадка работает только в режиме «${onlyMode}» — переключите режим выше`);
            else if (partial) tooltipParts.push(`У площадки ${reasons.join("; ")}. Можно выбрать — она будет пропущена для несовместимых параметров.`);
            else if (caveat) tooltipParts.push(caveat);
            const titleStr = tooltipParts.join("\n") || undefined;
            return (
              <m.button
                key={p}
                type="button"
                disabled={incompatible}
                onClick={() => toggleProvider(p)}
                whileHover={incompatible ? undefined : { scale: 1.04 }}
                whileTap={incompatible ? undefined : { scale: 0.96 }}
                title={titleStr}
                className={[
                  "flex items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-semibold capitalize transition-colors",
                  incompatible
                    ? "cursor-not-allowed border-white/5 bg-white/[0.02] text-muted/40"
                    : partial
                      ? (active
                          ? "border-amber-400/40 bg-amber-500/15 text-white"
                          : "border-amber-400/20 bg-amber-500/[0.06] text-muted hover:text-ink")
                      : active
                        ? "border-ocean/40 bg-ocean/15 text-white"
                        : "border-white/10 bg-white/[0.03] text-muted hover:text-ink",
                ].join(" ")}
              >
                <span
                  className={`size-2 rounded-full ${
                    incompatible
                      ? "bg-muted/20"
                      : active
                        ? "bg-ocean shadow-[0_0_10px_2px_rgba(56,224,216,0.6)]"
                        : "bg-muted/40"
                  }`}
                />
                {providerLabel(p)}
                {incompatible && onlyMode && (
                  <span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold normal-case tracking-wide text-muted/70">
                    только {onlyMode}
                  </span>
                )}
                {partial && (
                  <span title={titleStr}
                        className="rounded-md bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300"
                  >
                    ⚠
                  </span>
                )}
              </m.button>
            );
          })}
        </div>

        {/* Видимый баннер: какие из ВЫБРАННЫХ площадок будут пропущены и почему
            (audit-2026-06 — раньше только нативный title-tooltip, не виден на mobile). */}
        {(() => {
          const skipped = providers
            .map((p) => ({
              provider: p,
              reasons: incompatReasons(providerCoverage, p, {
                city: !isHotels ? departureCity : undefined,
                country: batch ? undefined : destinationCountry,
                mode,
                operators,
              }),
            }))
            .filter((s) => s.reasons.length > 0);
          if (!skipped.length) return null;
          return (
            <div className="mt-2 rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-100">
              <div className="mb-1 font-semibold">⚠ Не все выбранные площадки совместимы:</div>
              <ul className="space-y-0.5 text-amber-100/90">
                {skipped.map((s) => (
                  <li key={s.provider}>
                    <span className="font-semibold capitalize">{providerLabel(s.provider)}</span>: {s.reasons.join("; ")}
                  </li>
                ))}
              </ul>
            </div>
          );
        })()}
      </m.div>

      {/* Кнопка сабмита — крупная, с микроинтеракцией и состоянием загрузки */}
      <m.button
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
      </m.button>

      <HealthCheckInfo providers={providers} />
    </GlassCard>
  );
}

export default memo(SearchForm);

/**
 * HealthCheckInfo — раскрывающийся блок: коротко о том, что делает health-check.
 * Проверяются ТОЛЬКО выбранные площадки (в коде run_health_check(providers=chosen)).
 */
function HealthCheckInfo({ providers = [] }) {
  const [open, setOpen] = useState(false);

  return (
    <m.div variants={fadeUp} className="mt-3">
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
          <m.div
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
                  ? <>: <span className="capitalize text-ink">{providers.map(providerLabel).join(", ")}</span>.</>
                  : " (отметь площадки ниже)."}
              </p>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </m.div>
  );
}

/** Кастомный чекбокс в фирменном стиле. */
function Checkbox({ name, label, defaultChecked = false }) {
  const [checked, setChecked] = useState(defaultChecked);
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink">
      <input type="checkbox" name={name} defaultChecked={defaultChecked} className="peer sr-only" onChange={(e) => setChecked(e.target.checked)} />
      <m.span
        whileTap={{ scale: 0.85 }}
        className={[
          "grid size-5 place-items-center rounded-md border transition-colors",
          checked ? "border-brand bg-brand" : "border-white/20 bg-white/[0.04]",
        ].join(" ")}
      >
        <AnimatePresence>
          {checked && (
            <m.svg
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0, opacity: 0 }}
              className="size-3.5 text-white" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="3"
            >
              <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
            </m.svg>
          )}
        </AnimatePresence>
      </m.span>
      {label}
    </label>
  );
}
