import { useEffect, useRef, useState } from "react";
import DashboardLayout from "../components/DashboardLayout.jsx";
import SearchForm from "../components/SearchForm.jsx";
import SearchTerminal from "../components/SearchTerminal.jsx";
import LiveViews from "../components/LiveViews.jsx";
import { navigate } from "../lib/router.js";
import { takeRepeat } from "../lib/repeatStore.js";
import { PROVIDERS } from "../lib/constants.js";

let logSeq = 0;
const now = () => new Date().toTimeString().slice(0, 8);

/** Параметры прогона (из истории) → payload для runRealSearch. */
function payloadFromParams(p) {
  return {
    mode: p.search_mode,
    departure_city: p.departure_city,
    destination_country: p.destination_country,
    date_from: p.date_from,
    date_to: p.date_to,
    nights_min: p.nights_min,
    nights_max: p.nights_max,
    adults: p.adults,
    child_ages: p.children_ages ?? [],
    price_max: p.price_max ?? null,
    operators: p.operators ?? [],
    charter_only: !!p.charter_only,
    direct_only: !!p.direct_only,
    providers: p.providers?.length ? p.providers : [...PROVIDERS],
  };
}

/**
 * SearchPage — экран поиска (три колонки: live-окна / форма / терминал логов).
 * Идёт на реальный бэкенд: POST /search/prepare → token → SSE /search/stream.
 * По «done» переходит на внутренний маршрут результатов #/run/{id}.
 */
export default function SearchPage() {
  const [status, setStatus] = useState("idle"); // idle|running|done|error|cancelled
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [activeProviders, setActiveProviders] = useState([]);
  const [frames, setFrames] = useState({});
  const [phases, setPhases] = useState({});
  const esRef = useRef(null);
  const tokenRef = useRef(null);
  // Параметры повтора прогона (из истории) — читаем один раз при монтировании.
  const [repeatInitial] = useState(() => takeRepeat());

  const pushLog = (msg, level = "info") =>
    setLogs((prev) => [...prev, { id: ++logSeq, msg, level, ts: now() }]);
  const setPhase = (p, phase) => setPhases((prev) => ({ ...prev, [p]: phase }));

  const handleSubmit = (payload) => {
    if (status === "running") return;
    setLogs([]);
    setFrames({});
    setProgress(0);
    setActiveProviders(payload.providers);
    setPhases(Object.fromEntries(payload.providers.map((p) => [p, "waiting"])));
    setStatus("running");
    runRealSearch(payload);
  };

  // Повтор прогона из истории: предзаполняем форму и сразу запускаем поиск.
  useEffect(() => {
    if (repeatInitial) {
      handleSubmit(payloadFromParams(repeatInitial));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCancel = async () => {
    pushLog("⏹ Останавливаю поиск…", "warning");
    if (tokenRef.current) {
      try {
        await fetch(`/search/cancel?token=${tokenRef.current}`, { method: "POST" });
      } catch {
        /* бэкенд закроет поток сам */
      }
    }
  };

  function closeStream() {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }

  function finish(result) {
    closeStream();
    setStatus(result);
    if (result === "done") setProgress(100);
  }

  async function runRealSearch(payload) {
    const fd = new FormData();
    fd.append("mode", payload.mode);
    fd.append("departure_city", payload.departure_city ?? "Москва");
    fd.append("destination_country", payload.destination_country ?? "Турция");
    fd.append("date_from", payload.date_from);
    fd.append("date_to", payload.date_to);
    fd.append("nights_min", payload.nights_min);
    fd.append("nights_max", payload.nights_max);
    fd.append("adults", payload.adults);
    (payload.child_ages ?? []).forEach((a) => fd.append("child_age", a));
    (payload.operators ?? []).forEach((o) => fd.append("operator", o));
    (payload.providers ?? []).forEach((p) => fd.append("provider", p));
    if (payload.price_max) fd.append("price_max", payload.price_max);
    if (payload.charter_only) fd.append("charter_only", "on");
    if (payload.direct_only) fd.append("direct_only", "on");

    let token;
    try {
      const resp = await fetch("/search/prepare", { method: "POST", body: fd });
      const data = await resp.json();
      if (data.error) {
        pushLog(data.error, "err");
        return finish("error");
      }
      token = data.token;
    } catch (err) {
      pushLog(`Не удалось связаться с бэкендом: ${err}`, "err");
      return finish("error");
    }
    tokenRef.current = token;
    setProgress(6);

    const total = (payload.providers ?? []).length || 1;
    let doneCount = 0;
    const es = new EventSource(`/search/stream?token=${token}`);
    esRef.current = es;

    es.onmessage = (m) => {
      let e;
      try {
        e = JSON.parse(m.data);
      } catch {
        return;
      }
      switch (e.type) {
        case "log": {
          const level = e.level === "WARNING" ? "warning" : "info";
          pushLog(e.msg, level);
          if (/health-check/i.test(e.msg)) setProgress((v) => Math.max(v, 10));
          else if (/Гейт пройден/i.test(e.msg)) setProgress((v) => Math.max(v, 20));
          else if (/search start|Запускаю поиск/i.test(e.msg)) {
            setProgress((v) => Math.max(v, 28));
            (payload.providers ?? []).forEach((p) => setPhase(p, "loading"));
          }
          const done = e.msg.match(/provider\s+(\w+)\s*:\s*(OK|FAIL)/i);
          if (done) {
            const [, name, verdict] = done;
            setPhase(name, "done");
            doneCount += 1;
            setProgress((v) => Math.max(v, 28 + Math.round((doneCount / total) * 68)));
            pushLog(`✓ ${name}: ${verdict}`, verdict.toUpperCase() === "OK" ? "ok" : "warning");
          }
          break;
        }
        case "frame":
          setFrames((f) => ({ ...f, [e.provider]: e.data }));
          break;
        case "gate_failed": {
          pushLog("✗ Health-check не пройден — структура форм площадок изменилась:", "err");
          Object.entries(e.detail ?? {}).forEach(([prov, miss]) =>
            pushLog(`   ${prov}: ${Array.isArray(miss) ? miss.join(", ") : miss}`, "err")
          );
          finish("error");
          break;
        }
        case "done":
          pushLog("✓ Готово — открываю результаты…", "ok");
          finish("done");
          navigate(`/run/${e.run_id}`);
          break;
        case "cancelled":
          pushLog(e.msg || "Поиск остановлен.", "warning");
          finish("cancelled");
          break;
        case "error":
          pushLog(e.msg || "Ошибка поиска.", "err");
          finish("error");
          break;
        default:
          break;
      }
    };

    es.onerror = () => {
      // esRef обнуляется в closeStream() при штатном завершении — значит, если он
      // ещё жив, это реальный обрыв (рестарт/краш бэкенда, сеть), а не нормальное
      // закрытие. НЕ зависим от `status`: на момент создания обработчика он ещё
      // "idle" (setStatus асинхронный), поэтому условие `status === "running"`
      // никогда не срабатывало и обрыв молча оставлял UI висеть на «Идёт поиск…».
      if (!esRef.current) return;
      pushLog("Соединение с потоком прервано.", "err");
      finish("error");
    };
  }

  return (
    <DashboardLayout
      left={<LiveViews providers={activeProviders} frames={frames} phases={phases} active={status !== "idle"} />}
      center={<SearchForm onSubmit={handleSubmit} isSearching={status === "running"} initial={repeatInitial} />}
      right={<SearchTerminal logs={logs} progress={progress} status={status} onCancel={handleCancel} />}
    />
  );
}
