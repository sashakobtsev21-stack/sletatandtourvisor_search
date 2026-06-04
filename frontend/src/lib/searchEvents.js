// Чистые помощники интерпретации событий SSE-потока поиска — вынесены из SearchPage,
// чтобы хрупкую логику прогресса/парсинга можно было тестировать без браузера и React.

/**
 * Минимальный «пол» прогресса по тексту лог-строки (вехи поиска). Возвращает 0, если
 * строка не является вехой. Прогресс-бар берёт Math.max(текущий, этот пол).
 */
export function progressFloorForLog(msg) {
  if (/health-check/i.test(msg)) return 10;
  if (/Гейт пройден/i.test(msg)) return 20;
  if (/search start|Запускаю поиск/i.test(msg)) return 28;
  return 0;
}

/** true, если строка лога означает «поиск стартовал» (площадки → фаза loading). */
export function isSearchStart(msg) {
  return /search start|Запускаю поиск/i.test(msg);
}

/**
 * Разобрать строку завершения площадки «provider <name>: OK|FAIL».
 * Возвращает { name, verdict: "OK"|"FAIL" } или null.
 */
export function parseProviderDone(msg) {
  const m = (msg || "").match(/provider\s+(\w+)\s*:\s*(OK|FAIL)/i);
  return m ? { name: m[1], verdict: m[2].toUpperCase() } : null;
}
