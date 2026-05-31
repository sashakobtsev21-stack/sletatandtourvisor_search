// Минимальный hash-роутер (без зависимостей): дашборд раздаётся как статика под
// /app, поэтому клиентские маршруты живут в hash (#/history, #/run/18) — работают
// без серверной настройки SPA-fallback.
import { useEffect, useState } from "react";

const current = () => window.location.hash.replace(/^#/, "") || "/";

export function useHashRoute() {
  const [path, setPath] = useState(current);
  useEffect(() => {
    const on = () => setPath(current());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return path; // "/", "/history", "/tests", "/run/18"
}

export function navigate(to) {
  const hash = to.startsWith("#") ? to : "#" + to;
  if (window.location.hash !== hash) window.location.hash = hash;
}

/** Вернуть id прогона, если маршрут вида /run/<id>, иначе null. */
export function matchRun(path) {
  const m = path.match(/^\/run\/(\d+)$/);
  return m ? Number(m[1]) : null;
}
