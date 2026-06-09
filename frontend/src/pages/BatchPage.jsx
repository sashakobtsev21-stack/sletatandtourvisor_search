import { useMemo, useState } from "react";
import { m } from "framer-motion";
import { Layers, Info, Plus, MapPin, Globe2, Calendar, Moon, Users, Server, Trash2 } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { Field, Input, Select } from "../components/ui/Field.jsx";
import { useRefData } from "../lib/refdata.js";
import { apiFetch } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { formatDate } from "../lib/format.js";
import { staggerContainer, fadeUp } from "../lib/animations.js";
import { incompatReasons, caveatOf } from "../lib/providerCoverage.js";

/**
 * BatchPage (#/batch) — мультипоиск с per-direction датами.
 *
 * До 2026-06: чипы выбранных стран + ОДНИ общие даты на всех. Сейчас: каждое
 * направление — отдельная строка со своими `departure_city`, `country`,
 * `date_from`, `date_to`, `nights_min`, `nights_max`. Остальные параметры
 * (туристы, операторы, фильтры, площадки) общие.
 *
 * UX: composer-строка сверху + список добавленных направлений + панель общих
 * параметров. По сабмиту POST /api/jobs (JSON body) → #/jobs/{id}.
 */

// Дефолтные даты: завтра — +7 дней (как в SearchForm).
const today = () => new Date();
const addDays = (d, n) => new Date(d.getTime() + n * 86_400_000);
const isoDate = (d) => d.toISOString().slice(0, 10);
const DEFAULT_FROM = isoDate(addDays(today(), 1));
const DEFAULT_TO = isoDate(addDays(today(), 8));

export default function BatchPage() {
  const { departureCities, countries, operators: refOps, providers: refProv,
          providerModes, providerCoverage } = useRefData();

  // Composer state — то, что сейчас в форме «новое направление».
  const [depCity, setDepCity] = useState("Москва");
  const [country, setCountry] = useState(countries?.[0] ?? "Турция");
  const [dateFrom, setDateFrom] = useState(DEFAULT_FROM);
  const [dateTo, setDateTo] = useState(DEFAULT_TO);
  const [nightsMin, setNightsMin] = useState(7);
  const [nightsMax, setNightsMax] = useState(10);

  // Список добавленных направлений.
  const [directions, setDirections] = useState([]);

  // Shared-параметры (общие для всех направлений).
  const [adults, setAdults] = useState(2);
  const [childAges, setChildAges] = useState([]);
  const [providers, setProviders] = useState([...(refProv ?? [])]);
  const [opsSelected, setOpsSelected] = useState([]);
  const [priceMax, setPriceMax] = useState("");
  const [charterOnly, setCharterOnly] = useState(false);
  const [directOnly, setDirectOnly] = useState(false);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Поддерживает ли площадка туры (в мультипоиске режим только tours — отели
  // не имеют батч-смысла без per-hotel дат).
  const providerSupportsTours = (p) =>
    (providerModes[p] ?? ["tours", "hotels"]).includes("tours");

  const toggleProvider = (p) => {
    if (!providerSupportsTours(p)) return;
    setProviders((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));
  };

  const toggleOperator = (op) =>
    setOpsSelected((prev) => (prev.includes(op) ? prev.filter((x) => x !== op) : [...prev, op]));

  const handleChildren = (n) => {
    setChildAges((prev) => Array.from({ length: n }, (_, i) => prev[i] ?? 7));
  };

  const addDirection = () => {
    if (!country || !dateFrom || !dateTo) return;
    if (dateFrom > dateTo) {
      setError("Дата «до» должна быть не раньше «от».");
      return;
    }
    const candidate = {
      country, departure_city: depCity,
      date_from: dateFrom, date_to: dateTo,
      nights_min: nightsMin, nights_max: nightsMax,
    };
    // Дубль (та же страна + те же даты + тот же город) → не добавляем.
    const isDup = directions.some(
      (d) => d.country === candidate.country
          && d.date_from === candidate.date_from
          && d.date_to === candidate.date_to
          && d.departure_city === candidate.departure_city,
    );
    if (isDup) {
      setError("Это направление уже в списке (та же страна, даты, город вылета).");
      return;
    }
    setError("");
    setDirections((prev) => [...prev, candidate]);
  };

  const removeDirection = (idx) =>
    setDirections((prev) => prev.filter((_, i) => i !== idx));

  const totalText = useMemo(() => {
    if (directions.length === 0) return "Пока ничего не добавлено";
    if (directions.length === 1) return "Добавлено 1 направление (нужно минимум 2)";
    return `Добавлено ${directions.length}`;
  }, [directions.length]);

  const canSubmit = directions.length >= 2 && providers.length > 0 && !busy;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");

    const shared = {
      mode: "tours",
      // departure_city уровня job — placeholder для shared SearchParams;
      // воркер override'ит для каждого direction.
      departure_city: directions[0].departure_city,
      // date_from/date_to уровня job — fallback на случай если у направления не задано;
      // у нас всегда задаются, но shared должны быть валидными для SearchParams.
      date_from: directions[0].date_from,
      date_to: directions[0].date_to,
      nights_min: directions[0].nights_min,
      nights_max: directions[0].nights_max,
      adults,
      child_age: childAges,
      provider: providers,
      operator: opsSelected,
      price_max: priceMax || undefined,
      charter_only: charterOnly ? "on" : undefined,
      direct_only: directOnly ? "on" : undefined,
    };

    try {
      const resp = await apiFetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shared, directions }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setError(data.error || data.detail || "Не удалось запустить мультипоиск.");
        setBusy(false);
        return;
      }
      navigate(`/jobs/${data.job_id}`);
    } catch (ex) {
      setError(`Не удалось связаться с бэкендом: ${ex}`);
      setBusy(false);
    }
  };

  return (
    <m.form
      onSubmit={handleSubmit}
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-3xl space-y-4"
    >
      <GlassCard variants={fadeUp} className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
          <Layers className="size-5 text-white" />
        </span>
        <div className="text-sm text-muted">
          <div className="font-semibold text-ink">Мультипоиск — сравнение по разным направлениям и датам</div>
          Каждое направление — со своими городом вылета и датами. Туристы, операторы и
          фильтры — общие. Каждое направление расходует 1 поиск.
        </div>
      </GlassCard>

      {/* Composer: добавить новое направление */}
      <GlassCard variants={fadeUp} className="space-y-4 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Plus className="size-4 text-brand-soft" /> Добавить направление
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Откуда" icon={MapPin}>
            <Select icon searchable value={depCity} onChange={(e) => setDepCity(e.target.value)}>
              {departureCities.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </Field>
          <Field label="Куда" icon={Globe2}>
            <Select icon searchable value={country} onChange={(e) => setCountry(e.target.value)}>
              {countries.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </Field>
          <Field label="Когда (от)" icon={Calendar}>
            <Input icon type="date" value={dateFrom} min={isoDate(today())}
                   onChange={(e) => {
                     const v = e.target.value;
                     setDateFrom(v);
                     if (v > dateTo) setDateTo(v);
                   }} />
          </Field>
          <Field label="Когда (до)" icon={Calendar}>
            <Input icon type="date" value={dateTo} min={dateFrom}
                   onChange={(e) => setDateTo(e.target.value)} />
          </Field>
          <Field label="Ночей (от)" icon={Moon}>
            <Input icon type="number" min={1} max={30} value={nightsMin}
                   onChange={(e) => {
                     const n = Number(e.target.value);
                     setNightsMin(n);
                     if (n > nightsMax) setNightsMax(n);
                   }} />
          </Field>
          <Field label="Ночей (до)" icon={Moon}>
            <Input icon type="number" min={nightsMin} max={30} value={nightsMax}
                   onChange={(e) => setNightsMax(Number(e.target.value))} />
          </Field>
        </div>
        <button
          type="button"
          onClick={addDirection}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-brand/40 bg-brand/15 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand/25"
        >
          <Plus className="size-4" /> Добавить в список
        </button>
      </GlassCard>

      {/* Список добавленных направлений */}
      <GlassCard variants={fadeUp} className="space-y-3 p-5">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-white">Выбранные направления</div>
          <div className="text-xs text-muted">{totalText}</div>
        </div>
        {directions.length === 0 ? (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-center text-xs text-muted">
            Заполните форму выше и нажмите «Добавить в список».
          </div>
        ) : (
          <ul className="space-y-2">
            {directions.map((d, i) => (
              <li
                key={`${d.country}-${d.date_from}-${d.date_to}-${d.departure_city}-${i}`}
                className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5"
              >
                <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand/15 text-xs font-bold text-brand-soft">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1 text-sm">
                  <div className="font-semibold text-white">
                    {d.departure_city} → {d.country}
                  </div>
                  <div className="truncate text-xs text-muted">
                    {formatDate(d.date_from)} — {formatDate(d.date_to)}
                    {" · "}{d.nights_min}–{d.nights_max} ноч.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeDirection(i)}
                  title="Убрать направление"
                  className="rounded-lg p-1.5 text-rose-300/70 transition-colors hover:bg-rose-500/10 hover:text-rose-200"
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </GlassCard>

      {/* Общие параметры */}
      <GlassCard variants={fadeUp} className="space-y-4 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Users className="size-4 text-brand-soft" /> Общие параметры (для всех направлений)
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Взрослых" icon={Users}>
            <Input icon type="number" min={1} max={6} value={adults}
                   onChange={(e) => setAdults(Number(e.target.value))} />
          </Field>
          <Field label="Детей" icon={Users}>
            <Select icon value={String(childAges.length)} onChange={(e) => handleChildren(Number(e.target.value))}>
              {[0, 1, 2, 3, 4].map((n) => <option key={n} value={String(n)}>{n}</option>)}
            </Select>
          </Field>
        </div>
        {childAges.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-4">
            {childAges.map((a, i) => (
              <Input key={i} type="number" min={0} max={17} value={a}
                     onChange={(e) => {
                       const v = Number(e.target.value);
                       setChildAges((prev) => prev.map((x, k) => (k === i ? v : x)));
                     }} />
            ))}
          </div>
        )}

        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted">
            <Server className="size-3.5" /> Площадки (нажмите чтобы переключить)
          </div>
          <div className="flex flex-wrap gap-2">
            {refProv.map((p) => {
              const on = providers.includes(p);
              const supported = providerSupportsTours(p);
              // По всем уже добавленным направлениям соберём непокрытые: чтобы знать
              // «эта площадка не поддерживает половину выбранного». Если direction'ов
              // нет — берём текущее значение composer'а как indicative.
              const dirsToCheck = directions.length
                ? directions
                : [{ departure_city: depCity, country }];
              const allReasons = new Set();
              dirsToCheck.forEach((d) => {
                incompatReasons(providerCoverage, p, {
                  city: d.departure_city, country: d.country, mode: "tours",
                }).forEach((r) => allReasons.add(r));
              });
              const partial = supported && allReasons.size > 0;
              const caveat = caveatOf(providerCoverage, p);
              const title = !supported
                ? "Не поддерживает туры"
                : partial
                  ? `У площадки ${[...allReasons].join("; ")}. Несовместимые направления будут пропущены.`
                  : caveat || undefined;
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => toggleProvider(p)}
                  disabled={!supported}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                    !supported
                      ? "border-white/5 bg-white/[0.02] text-muted/40"
                      : partial
                        ? on
                          ? "border-amber-400/40 bg-amber-500/15 text-white"
                          : "border-amber-400/20 bg-amber-500/[0.06] text-muted hover:bg-amber-500/10"
                        : on
                          ? "border-brand/40 bg-brand/15 text-white"
                          : "border-white/10 bg-white/[0.03] text-muted hover:bg-white/[0.06]"
                  }`}
                  title={title}
                >
                  {p}{partial && <span className="ml-1 text-amber-300">⚠</span>}
                </button>
              );
            })}
          </div>
        </div>

        <details className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
          <summary className="cursor-pointer text-xs font-medium text-muted">
            Дополнительные фильтры (опционально)
          </summary>
          <div className="mt-3 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Макс. цена, ₽">
                <Input type="number" min={0} step={1000} value={priceMax}
                       onChange={(e) => setPriceMax(e.target.value)}
                       placeholder="без ограничения" />
              </Field>
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-ink">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={charterOnly} onChange={(e) => setCharterOnly(e.target.checked)} />
                только чартеры
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={directOnly} onChange={(e) => setDirectOnly(e.target.checked)} />
                только прямые рейсы
              </label>
            </div>
            <div>
              <div className="mb-2 text-xs font-medium text-muted">Туроператоры (если ничего — все)</div>
              <div className="flex flex-wrap gap-2">
                {refOps.map((op) => {
                  const on = opsSelected.includes(op);
                  return (
                    <button
                      key={op}
                      type="button"
                      onClick={() => toggleOperator(op)}
                      className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                        on
                          ? "border-brand/40 bg-brand/15 text-white"
                          : "border-white/10 bg-white/[0.03] text-muted hover:bg-white/[0.06]"
                      }`}
                    >
                      {op}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </details>
      </GlassCard>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <Info className="size-4 shrink-0" /> {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean px-4 py-3 text-sm font-semibold text-white shadow-glow transition-opacity disabled:opacity-40"
      >
        {busy
          ? "Запускаю…"
          : directions.length >= 2
          ? `Запустить мультипоиск (${directions.length})`
          : "Добавьте минимум 2 направления"}
      </button>
    </m.form>
  );
}
