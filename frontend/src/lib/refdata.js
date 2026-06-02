// Справочники формы (города вылета, страны, операторы, площадки) — единый источник
// правды на бэкенде (refdata.py) через GET /api/refdata. Хардкод в constants.js
// остаётся ТОЛЬКО как фолбэк, если запрос не удался (офлайн/дев без бэкенда), —
// так фронт и бэкенд больше не расходятся вручную.
import { useEffect, useState } from "react";
import { DEPARTURE_CITIES, COUNTRIES, OPERATORS, PROVIDERS } from "./constants.js";

const FALLBACK = {
  departureCities: DEPARTURE_CITIES,
  countries: COUNTRIES,
  operators: OPERATORS,
  providers: PROVIDERS,
  experimentalProviders: [],
};

export function useRefData() {
  const [data, setData] = useState(FALLBACK);
  useEffect(() => {
    let alive = true;
    fetch("/api/refdata")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => {
        if (!alive) return;
        // Пустые/отсутствующие поля заменяем фолбэком, чтобы форма не осталась без данных.
        setData({
          departureCities: j.departure_cities?.length ? j.departure_cities : DEPARTURE_CITIES,
          countries: j.countries?.length ? j.countries : COUNTRIES,
          operators: j.operators?.length ? j.operators : OPERATORS,
          providers: j.providers?.length ? j.providers : PROVIDERS,
          experimentalProviders: j.experimental_providers ?? [],
        });
      })
      .catch(() => {
        /* фолбэк — константы (data уже инициализирован ими) */
      });
    return () => {
      alive = false;
    };
  }, []);
  return data;
}
