// Хелперы для проверки покрытия площадок (audit-2026-06).
// Данные приходят из /api/refdata через useRefData() → providerCoverage.
// Структура: { provider: { modes, departure_cities, countries, caveat } }
// Значение "all" означает «без ограничений».

/** Поддерживает ли площадка указанный город вылета. */
export function supportsCity(coverage, provider, city) {
  const info = coverage?.[provider];
  if (!info) return true;
  const cs = info.departure_cities;
  return cs === "all" || (Array.isArray(cs) && cs.includes(city));
}

/** Поддерживает ли площадка указанную страну. */
export function supportsCountry(coverage, provider, country) {
  const info = coverage?.[provider];
  if (!info) return true;
  const cs = info.countries;
  return cs === "all" || (Array.isArray(cs) && cs.includes(country));
}

/** Поддерживает ли площадка режим (tours/hotels). */
export function supportsMode(coverage, provider, mode) {
  const info = coverage?.[provider];
  if (!info) return true;
  const ms = info.modes;
  return !Array.isArray(ms) || ms.includes(mode);
}

/** Поддерживает ли площадка фильтр «по туроператору» (audit-2026-06). */
export function supportsOperatorFilter(coverage, provider) {
  const info = coverage?.[provider];
  if (!info) return true;                    // нет данных → считаем что да
  return info.operator_filter !== false;     // явный false → нет; undefined/true → да
}

/**
 * Собрать список причин почему площадка несовместима с выбором.
 * Возвращает [] если всё ok, или array строк-причин для tooltip.
 *
 * operators — список выбранных туроператоров; если непустой и площадка не
 * поддерживает фильтр — добавится причина (audit-2026-06).
 */
export function incompatReasons(coverage, provider, { city, country, mode, operators }) {
  const reasons = [];
  if (mode && !supportsMode(coverage, provider, mode)) {
    const info = coverage?.[provider];
    const supported = (info?.modes ?? []).join("/");
    reasons.push(`не поддерживает режим «${mode}» (только ${supported || "?"})`);
  }
  if (city && !supportsCity(coverage, provider, city)) {
    reasons.push(`нет города вылета «${city}»`);
  }
  if (country && !supportsCountry(coverage, provider, country)) {
    reasons.push(`нет направления «${country}»`);
  }
  if (operators && operators.length && !supportsOperatorFilter(coverage, provider)) {
    reasons.push(`не поддерживает фильтр по туроператору`);
  }
  return reasons;
}

/** Короткий caveat-хинт площадки (для tooltip когда совместима, но есть оговорки). */
export function caveatOf(coverage, provider) {
  return coverage?.[provider]?.caveat ?? "";
}
