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

// Активный прогон ВНЕ жизненного цикла компонента: позволяет вернуть «живой» поиск,
// если ушли на другую страницу приложения (История/Тесты) и вернулись назад. Поиск
// продолжается на сервере; здесь храним лишь токен и список площадок для реконнекта.
let activeRun = null; // { token, providers } | null

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
 *
 * Поиск устойчив к смене вкладки: на сервере он идёт фоновой задачей и не привязан к
 * соединению. Если SSE оборвался (увели вкладку, сеть моргнула) — мы НЕ считаем это
 * ошибкой: EventSource переподключается сам, а сервер присылает «переигровку» всего
 * прогресса (маркер replay_start → сброс и пересборка состояния) и продолжение. При
 * возврате на вкладку/страницу поиска переподключаемся принудительно, если нужно.
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
  const statusRef = useRef("idle"); // зеркало status для слушателей (visibilitychange)
  const providersRef = useRef([]); // площадки текущего прогона (для сброса фаз при реконнекте)
  const reconnRef = useRef(false); // «переподключаюсь…» показываем один раз за обрыв
  // Параметры повтора прогона (из истории) — читаем один раз при монтировании.
  const [repeatInitial] = useState(() => takeRepeat());

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const pushLog = (msg, level = "info") =>
    setLogs((prev) => [...prev, { id: ++logSeq, msg, level, ts: now() }]);
  const setPhase = (p, phase) => setPhases((prev) => ({ ...prev, [p]: phase }));

  const handleSubmit = (payload) => {
    if (status === "running") return;
    setLogs([]);
    setFrames({});
    setProgress(0);
    setActiveProviders(payload.providers);
    providersRef.current = payload.providers;
    setPhases(Object.fromEntries(payload.providers.map((p) => [p, "waiting"])));
    setStatus("running");
    runRealSearch(payload);
  };

  // Монтирование: либо повтор из истории (новый поиск), либо возврат к ещё идущему
  // прогону (ушли на другую страницу приложения и вернулись) — переподключаемся.
  useEffect(() => {
    if (repeatInitial) {
      handleSubmit(payloadFromParams(repeatInitial));
      return;
    }
    if (activeRun) {
      setActiveProviders(activeRun.providers);
      providersRef.current = activeRun.providers;
      setPhases(Object.fromEntries(activeRun.providers.map((p) => [p, "waiting"])));
      setStatus("running");
      tokenRef.current = activeRun.token;
      connectStream(activeRun.token);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Возврат на вкладку браузера: если поток закрыт, а поиск ещё идёт — переподключаемся.
  // (EventSource обычно реконнектится сам; это страховка на случай, когда браузер
  // полностью усыпил вкладку и закрыл соединение.)
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (statusRef.current !== "running" || !tokenRef.current) return;
      const es = esRef.current;
      if (!es || es.readyState === EventSource.CLOSED) connectStream(tokenRef.current);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Размонтирование страницы (ушли в Историю/Тесты): закрываем поток, но прогон на
  // сервере продолжается — activeRun остаётся, чтобы можно было вернуться к нему.
  useEffect(() => () => closeStream(), []); // eslint-disable-line react-hooks/exhaustive-deps

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
    activeRun = null; // прогон завершён — нечего восстанавливать
    setStatus(result);
    if (result === "done") setProgress(100);
  }

  // Создать (или пересоздать) SSE-поток для токена. Идемпотентно по состоянию: на каждом
  // (пере)подключении сервер шлёт replay_start + переигровку, и мы строим живое состояние
  // заново — без дублей в логе и без двойного счёта площадок.
  function connectStream(token) {
    closeStream();
    const providers = providersRef.current;
    const total = providers.length || 1;
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
      reconnRef.current = false; // пришли данные → соединение живо
      switch (e.type) {
        case "replay_start":
          // (пере)подключились — сбрасываем живое состояние, переигровка построит заново
          doneCount = 0;
          setLogs([]);
          setFrames({});
          setProgress(6);
          setPhases(Object.fromEntries(providers.map((p) => [p, "waiting"])));
          break;
        case "log": {
          const level = e.level === "WARNING" ? "warning" : "info";
          pushLog(e.msg, level);
          if (/health-check/i.test(e.msg)) setProgress((v) => Math.max(v, 10));
          else if (/Гейт пройден/i.test(e.msg)) setProgress((v) => Math.max(v, 20));
          else if (/search start|Запускаю поиск/i.test(e.msg)) {
            setProgress((v) => Math.max(v, 28));
            providers.forEach((p) => setPhase(p, "loading"));
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
          if (/истёк токен/i.test(e.msg || "")) {
            // Сессия уже завершилась и убрана (вернулись поздно) — прогон в Истории.
            pushLog("Этот прогон уже завершён — найдите его в Истории.", "info");
            closeStream();
            activeRun = null;
            setStatus("idle");
            return;
          }
          pushLog(e.msg || "Ошибка поиска.", "err");
          finish("error");
          break;
        default:
          break;
      }
    };

    es.onerror = () => {
      if (!esRef.current) return; // мы сами закрыли поток — игнорируем
      if (es.readyState === EventSource.CLOSED) {
        // Окончательный отказ (сервер вернул ошибку/недоступен) — не висим молча.
        pushLog("Соединение с потоком закрыто.", "err");
        finish("error");
      } else if (!reconnRef.current) {
        // Временный обрыв (увели вкладку, сеть моргнула): EventSource переподключится сам,
        // поиск на сервере продолжается; по реконнекту получим переигровку прогресса.
        reconnRef.current = true;
        pushLog("Соединение прервано — переподключаюсь, поиск продолжается…", "warning");
      }
    };
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
    providersRef.current = payload.providers ?? [];
    activeRun = { token, providers: payload.providers ?? [] };
    setProgress(6);
    connectStream(token);
  }

  return (
    <DashboardLayout
      left={<LiveViews providers={activeProviders} frames={frames} phases={phases} active={status === "running"} />}
      center={<SearchForm onSubmit={handleSubmit} isSearching={status === "running"} initial={repeatInitial} />}
      right={<SearchTerminal logs={logs} progress={progress} status={status} onCancel={handleCancel} />}
    />
  );
}
