// Единая обёртка над fetch для общения с бэкендом под авторизацией.
//  • credentials: 'include' — cookie-сессия (ts_session) едет сама на тот же origin;
//  • на мутирующих методах подставляем X-CSRF-Token из НЕ-httponly cookie ts_csrf
//    (double-submit: бэкенд сверяет заголовок с cookie);
//  • timeoutMs (по умолчанию 30с) — внутренний AbortController сам отменит зависший
//    запрос; внешний opts.signal комбинируется (отменится по любому);
//  • retry на 429 / 502 / 503 / 504 — только для safe-методов (GET/HEAD), backoff
//    экспонентой 500мс·2^n, либо берётся из Retry-After. Unsafe не ретраим
//    автоматически (риск двойного списания/двойного создания); явный opt-in:
//    apiFetch(url, { method:'POST', retry:true }).
//  • на 401 (кроме самого логина) дёргаем обработчик «разлогинен» → UI показывает вход.
// Content-Type НЕ трогаем: для FormData его ставит браузер (с boundary), для JSON — вызывающий.

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const SAFE = new Set(["GET", "HEAD"]);
const RETRY_STATUSES = new Set([429, 502, 503, 504]);
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 2;                   // итого до 3 попыток на retriable

let _onUnauthorized = () => {};

/** Зарегистрировать реакцию на 401 (AuthProvider ставит сюда setUser(null)). */
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = typeof fn === "function" ? fn : () => {};
}

function getCookie(name) {
  const m = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
  return m ? decodeURIComponent(m[1]) : "";
}

// Sleep с поддержкой отмены через AbortSignal — чтобы во время backoff'а внешняя
// отмена (закрытие страницы / новый запрос) не висела впустую таймером.
function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    if (!signal) return;
    if (signal.aborted) { clearTimeout(t); reject(new DOMException("aborted", "AbortError")); return; }
    const onAbort = () => { clearTimeout(t); reject(new DOMException("aborted", "AbortError")); };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function apiFetch(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = new Headers(opts.headers || {});
  if (UNSAFE.has(method)) {
    const csrf = getCookie("ts_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const externalSignal = opts.signal;
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  // По умолчанию retry'им safe-методы; для unsafe — только если явно opts.retry:true.
  const retryEnabled = opts.retry === undefined ? SAFE.has(method) : Boolean(opts.retry);

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(
      () => ctrl.abort(new DOMException("timeout", "TimeoutError")),
      timeoutMs,
    );
    const onExternalAbort = () => ctrl.abort();
    if (externalSignal) {
      if (externalSignal.aborted) ctrl.abort();
      else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
    try {
      const res = await fetch(url, {
        ...opts, method, headers, credentials: "include", signal: ctrl.signal,
      });
      if (res.status === 401 && !url.includes("/api/login")) _onUnauthorized();
      if (retryEnabled && RETRY_STATUSES.has(res.status) && attempt < MAX_RETRIES) {
        const retryAfter = parseInt(res.headers.get("Retry-After") || "", 10);
        const backoffMs = !Number.isNaN(retryAfter)
          ? retryAfter * 1000
          : 500 * 2 ** attempt;
        await delay(backoffMs, externalSignal);
        continue;
      }
      return res;
    } catch (err) {
      lastError = err;
      // AbortError — пользователь/таймаут отменил, не ретраим (это сознательная остановка).
      // Сетевые ошибки (TypeError "Failed to fetch") — transient, ретраим если разрешено.
      if (!retryEnabled || attempt >= MAX_RETRIES || err.name === "AbortError") throw err;
      await delay(500 * 2 ** attempt, externalSignal);
    } finally {
      clearTimeout(timer);
      if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }
  throw lastError;
}
