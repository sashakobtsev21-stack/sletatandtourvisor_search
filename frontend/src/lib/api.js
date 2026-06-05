// Единая обёртка над fetch для общения с бэкендом под авторизацией.
//  • credentials: 'include' — cookie-сессия (ts_session) едет сама на тот же origin;
//  • на мутирующих методах подставляем X-CSRF-Token из НЕ-httponly cookie ts_csrf
//    (double-submit: бэкенд сверяет заголовок с cookie);
//  • на 401 (кроме самого логина) дёргаем обработчик «разлогинен» → UI показывает вход.
// Content-Type НЕ трогаем: для FormData его ставит браузер (с boundary), для JSON — вызывающий.

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let _onUnauthorized = () => {};

/** Зарегистрировать реакцию на 401 (AuthProvider ставит сюда setUser(null)). */
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = typeof fn === "function" ? fn : () => {};
}

function getCookie(name) {
  const m = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
  return m ? decodeURIComponent(m[1]) : "";
}

export async function apiFetch(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = new Headers(opts.headers || {});
  if (UNSAFE.has(method)) {
    const csrf = getCookie("ts_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(url, { ...opts, method, headers, credentials: "include" });
  if (res.status === 401 && !url.includes("/api/login")) _onUnauthorized();
  return res;
}
