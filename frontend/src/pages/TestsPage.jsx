import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  FlaskConical, Play, Loader2, CheckCircle2, XCircle, ChevronDown, Info, Clock,
  ShieldCheck, Zap, Globe2,
} from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { fadeUp } from "../lib/animations.js";

// Три верхнеуровневых списка вкладки (изначально свёрнуты). Порядок показа:
// health-check → быстрые → live (по просьбе; быстрые всё равно бегут первыми).
const CATEGORIES = [
  {
    key: "healthcheck", title: "Тесты health-check", icon: ShieldCheck,
    hint: "Проверяют, что формы площадок целы. Ниже — что именно проверяем и какими селекторами. Live ⏱ реально открывают сайт.",
  },
  {
    key: "fast", title: "Быстрые автотесты", icon: Zap,
    hint: "Без браузера, мгновенные: проверяют, что наша логика обработки данных не сломана.",
  },
  {
    key: "live", title: "Live-тесты Sletat", icon: Globe2,
    hint: "⏱ Реальные поиски на Sletat.ru по параметрам с проверкой результата (медленные).",
  },
];

/** TestsPage — каталог автотестов (#/tests): выбор групп/кейсов, прогон по SSE. */
export default function TestsPage() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [openInfo, setOpenInfo] = useState(() => new Set());
  const [statuses, setStatuses] = useState({}); // id -> {state:'run'|'pass'|'fail', error?}
  const [running, setRunning] = useState(false);
  const [stats, setStats] = useState({ passed: 0, failed: 0, total: 0, done: 0, duration: null });
  const [current, setCurrent] = useState("—");
  const [logs, setLogs] = useState([]);
  const [report, setReport] = useState(null);
  const logRef = useRef(null);
  const esRef = useRef(null);

  useEffect(() => {
    fetch("/api/tests/catalog")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setCatalog)
      .catch((e) => setError(String(e)));
    return () => esRef.current?.close();
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs.length]);

  const allIds = useMemo(
    () => (catalog ? catalog.groups.flatMap((g) => g.cases.map((c) => c.id)) : []),
    [catalog]
  );

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleGroup = (group, on) =>
    setSelected((prev) => {
      const next = new Set(prev);
      group.cases.forEach((c) => (on ? next.add(c.id) : next.delete(c.id)));
      return next;
    });

  const toggleAll = (on) => setSelected(on ? new Set(allIds) : new Set());

  const groupsOf = (catKey) =>
    (catalog?.groups ?? []).filter((g) => (g.category || "fast") === catKey);

  const toggleCategory = (catKey, on) =>
    setSelected((prev) => {
      const next = new Set(prev);
      groupsOf(catKey).forEach((g) => g.cases.forEach((c) => (on ? next.add(c.id) : next.delete(c.id))));
      return next;
    });

  const toggleInfo = (id) =>
    setOpenInfo((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const pushLog = (msg, cls = "") => setLogs((prev) => [...prev, { id: prev.length, msg, cls }]);

  function runSelected() {
    const ids = [...selected];
    if (!ids.length) {
      pushLog("Не выбрано ни одного теста.", "fail");
      return;
    }
    setStatuses({});
    setStats({ passed: 0, failed: 0, total: ids.length, done: 0, duration: null });
    setCurrent("—");
    setLogs([]);
    setReport(null);
    setRunning(true);

    let passed = 0, failed = 0, done = 0;
    const total = ids.length;

    fetch("/tests/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    })
      .then((r) => r.json())
      .then(({ token }) => {
        const es = new EventSource(`/tests/stream?token=${token}`);
        esRef.current = es;
        es.onmessage = (m) => {
          const e = JSON.parse(m.data);
          if (e.type === "running") {
            setCurrent(`[${e.group}] ${e.name}`);
            setStatuses((s) => ({ ...s, [e.id]: { state: "run" } }));
            pushLog(`▷ [${e.group}] ${e.name}`, "run");
          } else if (e.type === "result") {
            done += 1;
            if (e.ok) {
              passed += 1;
              setStatuses((s) => ({ ...s, [e.id]: { state: "pass" } }));
            } else {
              failed += 1;
              setStatuses((s) => ({ ...s, [e.id]: { state: "fail", error: e.error } }));
              pushLog(`  ✗ ${e.error || ""}`, "fail");
            }
            setStats({ passed, failed, total, done, duration: null });
          } else if (e.type === "end") {
            es.close();
            esRef.current = null;
            setRunning(false);
            setCurrent("— готово —");
            setStats({ passed: e.passed, failed: e.failed, total: e.total, done: e.total, duration: e.duration });
            setReport(e);
            pushLog(`— завершено за ${e.duration} c —`);
          }
        };
        es.onerror = () => {
          es.close();
          esRef.current = null;
          setRunning(false);
          pushLog("[поток прерван]", "fail");
        };
      })
      .catch((err) => {
        setRunning(false);
        pushLog(`Ошибка запуска: ${err}`, "fail");
      });
  }

  if (error) return <Center text={`Не удалось загрузить каталог тестов: ${error}`} tone="err" />;
  if (!catalog) return <Center text="Загружаю каталог тестов…" spin />;

  const pct = stats.total ? Math.round((stats.done / stats.total) * 100) : 0;
  const allChecked = selected.size === allIds.length && allIds.length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      {/* Тулбар */}
      <GlassCard variants={fadeUp} initial="hidden" animate="show" className="p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <FlaskConical className="size-5 text-white" />
          </span>
          <div>
            <h2 className="text-xl font-extrabold tracking-tight text-white">Автотесты</h2>
            <p className="text-xs text-muted">Каталог из {catalog.total} кейсов · выбрано {selected.size}</p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={allChecked} onChange={(e) => toggleAll(e.target.checked)} className="size-4 accent-brand" />
              Выбрать все
            </label>
            <button
              onClick={runSelected}
              disabled={running || selected.size === 0}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand-deep to-brand px-4 py-2 text-sm font-bold text-white shadow-glow transition-opacity disabled:opacity-50"
            >
              {running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
              Запустить выбранные
            </button>
          </div>
        </div>

        {/* Прогресс */}
        <div className="mt-4 flex items-center gap-4">
          <span className="min-w-[3.5rem] text-2xl font-extrabold tabular-nums text-white">{pct}%</span>
          <div className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
            <motion.span
              className={`absolute inset-y-0 left-0 rounded-full ${stats.failed ? "bg-gradient-to-r from-emerald-400 to-rose-400" : "bg-gradient-to-r from-brand to-ocean"}`}
              animate={{ width: `${pct}%` }}
              transition={{ type: "spring", stiffness: 120, damping: 20 }}
            />
          </div>
          <span className="whitespace-nowrap text-sm text-muted">
            прошло <b className="text-emerald-300">{stats.passed}</b> · упало <b className="text-rose-300">{stats.failed}</b> · из <b className="text-ink">{stats.total}</b>
            {stats.duration != null && <span className="ml-2 text-muted">{stats.duration} c</span>}
          </span>
        </div>
        <p className="mt-2 text-xs text-muted">Сейчас: <span className="text-ink">{current}</span></p>
      </GlassCard>

      {/* Лог */}
      <GlassCard variants={fadeUp} initial="hidden" animate="show" className="p-4">
        <h3 className="mb-2 text-sm font-bold text-white">Лог выполнения</h3>
        <div ref={logRef} className="h-40 overflow-y-auto rounded-xl bg-[#070b1c]/80 p-3 font-mono text-xs leading-relaxed shadow-inset-terminal">
          {logs.length === 0 ? (
            <span className="text-muted">Лог появится здесь во время прогона…</span>
          ) : (
            logs.map((l) => (
              <div key={l.id} className={LOG_COLORS[l.cls] || "text-sky-200"}>{l.msg}</div>
            ))
          )}
        </div>
      </GlassCard>

      {/* Три категории — изначально свёрнуты: health-check / быстрые / live. */}
      <div className="space-y-3">
        {CATEGORIES.map((cat) => {
          const cgroups = groupsOf(cat.key);
          if (!cgroups.length) return null;
          const cids = cgroups.flatMap((g) => g.cases.map((c) => c.id));
          const catChecked = cids.length > 0 && cids.every((id) => selected.has(id));
          const Icon = cat.icon;
          return (
            <GlassCard key={cat.key} variants={fadeUp} initial="hidden" animate="show" className="p-0">
              <details className="group/cat overflow-hidden rounded-xl2">
                <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5 hover:bg-white/[0.03]">
                  <input
                    type="checkbox" checked={catChecked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => toggleCategory(cat.key, e.target.checked)}
                    className="size-4 accent-brand"
                  />
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand/30 to-ocean/20">
                    <Icon className="size-4.5 text-brand-soft" />
                  </span>
                  <ChevronDown className="size-4 shrink-0 text-muted transition-transform group-open/cat:rotate-180" />
                  <div className="min-w-0 flex-1">
                    <div className="font-bold text-white">{cat.title}</div>
                    <div className="text-xs text-muted">{cat.hint}</div>
                  </div>
                  <span className="ml-auto shrink-0 rounded-full bg-white/[0.06] px-2.5 py-0.5 text-xs font-semibold text-muted">
                    {cids.length}
                  </span>
                </summary>

                <div className="border-t border-white/5 p-2">
                  {cat.key === "healthcheck" && <AnchorsInfo anchors={catalog.healthcheck_anchors} />}
                  {cgroups.map((g) => {
                    const groupChecked = g.cases.every((c) => selected.has(c.id));
                    return (
                      <details key={g.group} className="group border-b border-white/5 last:border-0">
                        <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2.5 hover:bg-white/[0.03]">
                          <input
                            type="checkbox" checked={groupChecked}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => toggleGroup(g, e.target.checked)}
                            className="size-4 accent-brand"
                          />
                          <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" />
                          <span className="font-semibold text-ink">{g.group}</span>
                          <span className="text-xs text-muted">({g.cases.length})</span>
                        </summary>
                        <div className="px-4 pb-3">
                          {g.description && <p className="mb-2 whitespace-pre-wrap pl-6 text-xs text-muted">{g.description}</p>}
                          {g.cases.map((c) => {
                            const st = statuses[c.id];
                            return (
                              <div key={c.id} className="flex flex-wrap items-center gap-2 py-1 pl-6 text-sm">
                                <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} className="size-3.5 accent-brand" />
                                <StatusIcon st={st} />
                                <span className={c.live ? "text-amber-300" : "text-ink/90"}>{c.name}{c.live && " ⏱"}</span>
                                {c.description && (
                                  <button type="button" onClick={() => toggleInfo(c.id)} className="grid size-4 place-items-center rounded-full border border-white/15 text-[10px] font-bold text-brand-soft hover:bg-white/5" title="Что проверяет тест">
                                    <Info className="size-2.5" />
                                  </button>
                                )}
                                {st?.state === "fail" && st.error && <span className="basis-full pl-6 text-xs text-rose-300/90">{st.error}</span>}
                                {openInfo.has(c.id) && c.description && (
                                  <span className="basis-full whitespace-pre-wrap rounded-r-md border-l-2 border-brand/60 bg-white/[0.03] py-1.5 pl-3 pr-2 text-xs text-muted">{c.description}</span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </details>
                    );
                  })}
                </div>
              </details>
            </GlassCard>
          );
        })}
      </div>

      {/* Отчёт */}
      {report && (
        <GlassCard variants={fadeUp} initial="hidden" animate="show" className="p-5">
          <h3 className="mb-2 text-sm font-bold text-white">Отчёт</h3>
          <p className="text-sm text-ink">
            Итог: прошло <b className="text-emerald-300">{report.passed}</b> / упало <b className="text-rose-300">{report.failed}</b> из {report.total} за {report.duration} c
          </p>
          {report.failures?.length ? (
            <div className="mt-3 space-y-1.5">
              {report.failures.map((f, i) => (
                <div key={i} className="rounded-lg border border-rose-400/20 bg-rose-500/10 p-2.5 text-xs">
                  <div className="font-semibold text-rose-200">✗ [{f.group}] {f.name}</div>
                  <div className="mt-0.5 font-mono text-rose-300/80">{f.error}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-emerald-300">Все выбранные тесты прошли ✅</p>
          )}
        </GlassCard>
      )}
    </div>
  );
}

/** Блок «что проверяет health-check»: якоря (поля + селекторы) по площадкам. */
function AnchorsInfo({ anchors }) {
  const blocks = Object.entries(anchors || {});
  if (!blocks.length) return null;
  return (
    <div className="mx-1 mb-2 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs">
      <p className="mb-2.5 text-muted">
        Health-check проверяет, что в форме площадки на месте эти поля (якоря). Если какой-то
        селектор пропал — сайт сменил вёрстку, и поиск блокируется, чтобы не искать вслепую.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {blocks.map(([prov, list]) => (
          <div key={prov}>
            <div className="mb-1.5 flex items-center gap-1.5 font-semibold capitalize text-ink">
              <ShieldCheck className="size-3.5 text-ocean" /> {prov}
            </div>
            <ul className="space-y-1">
              {list.map((a) => (
                <li key={a.selector} className="flex items-center justify-between gap-2">
                  <span className="text-muted">{a.label}</span>
                  <code className="truncate rounded bg-black/30 px-1.5 py-0.5 font-mono text-[10px] text-brand-soft">
                    {a.selector}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-2.5 flex items-center gap-1.5 text-[11px] text-amber-300/90">
        <Zap className="size-3" /> При запуске любого health-check сначала автоматически
        прогоняются все быстрые тесты.
      </p>
    </div>
  );
}

const LOG_COLORS = { run: "text-sky-300", fail: "text-rose-300", pass: "text-emerald-300" };

function StatusIcon({ st }) {
  if (!st) return <span className="w-4 text-center text-muted">·</span>;
  if (st.state === "run") return <Loader2 className="size-3.5 animate-spin text-sky-300" />;
  if (st.state === "pass") return <CheckCircle2 className="size-3.5 text-emerald-300" />;
  return <XCircle className="size-3.5 text-rose-300" />;
}

function Center({ text, spin = false, tone }) {
  const Icon = spin ? Loader2 : FlaskConical;
  return (
    <div className="mx-auto max-w-2xl">
      <GlassCard className="p-10">
        <div className={`flex flex-col items-center gap-3 text-center ${tone === "err" ? "text-rose-300" : "text-muted"}`}>
          <Icon className={`size-8 ${spin ? "animate-spin" : ""}`} />
          <p className="text-sm">{text}</p>
        </div>
      </GlassCard>
    </div>
  );
}
