import { useRef, useState } from "react";
import DashboardLayout from "./components/DashboardLayout.jsx";
import SearchForm from "./components/SearchForm.jsx";
import SearchTerminal from "./components/SearchTerminal.jsx";
import LiveViews from "./components/LiveViews.jsx";

let logSeq = 0;
const now = () => new Date().toTimeString().slice(0, 8);

/**
 * App — корневой контейнер дашборда: хранит состояние поиска и раскладывает
 * три панели по слотам DashboardLayout.
 *
 * Поиск идёт через РЕАЛЬНЫЙ бэкенд (FastAPI): POST /search/prepare → token,
 * затем SSE GET /search/stream?token=… транслирует health-check, живые кадры
 * площадок и логи. По «done» переходим на серверную страницу результатов
 * /run/{id}. В dev фронт (vite :5173) проксирует эти пути на бэкенд (vite.config.js).
 */
export default function App() {
  const [status, setStatus] = useState("idle"); // idle|running|done|error|cancelled
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [activeProviders, setActiveProviders] = useState([]);
  const [frames, setFrames] = useState({});
  // Фаза каждой площадки для live-окна: waiting | loading | done.
  const [phases, setPhases] = useState({});
  const esRef = useRef(null);
  const tokenRef = useRef(null);

  const pushLog = (msg, level = "info") =>
    setLogs((prev) => [...prev, { id: ++logSeq, msg, level, ts: now() }]);

  const setPhase = (p, phase) => setPhases((prev) => ({ ...prev, [p]: phase }));

  const handleSubmit = (payload) => {
    if (status === "running") return;
    // сброс
    setLogs([]);
    setFrames({});
    setProgress(0);
    setActiveProviders(payload.providers);
    setPhases(Object.fromEntries(payload.providers.map((p) => [p, "waiting"])));
    setStatus("running");
    runRealSearch(payload);
  };

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

  // --- Реальное подключение к бэкенду (FastAPI, SSE) ----------------------
  async function runRealSearch(payload) {
    // Собираем multipart-форму в формате, который ждёт /search/prepare:
    // повторяемые поля provider/operator/child_age, флаги — только когда включены.
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
          // прогресс по вехам потока
          if (/health-check/i.test(e.msg)) setProgress((v) => Math.max(v, 10));
          else if (/Гейт пройден/i.test(e.msg)) setProgress((v) => Math.max(v, 20));
          else if (/search start|Запускаю поиск/i.test(e.msg)) {
            setProgress((v) => Math.max(v, 28));
            (payload.providers ?? []).forEach((p) => setPhase(p, "loading"));
          }
          // завершение конкретной площадки: «provider <name>: OK|FAIL …»
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
          window.location = `/run/${e.run_id}`;
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
      // Поток закрыт сервером после завершения, либо обрыв связи.
      if (status === "running" && esRef.current) {
        pushLog("Соединение с потоком прервано.", "err");
        finish("error");
      }
    };
  }

  return (
    <DashboardLayout
      left={<LiveViews providers={activeProviders} frames={frames} phases={phases} active={status !== "idle"} />}
      center={<SearchForm onSubmit={handleSubmit} isSearching={status === "running"} />}
      right={
        <SearchTerminal logs={logs} progress={progress} status={status} onCancel={handleCancel} />
      }
    />
  );
}
