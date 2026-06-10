// Единая карта статусов мультипоиска (batch job). Источник статусов — бэкенд:
// storage.py (jobs.status: pending/running/done/partial/failed/interrupted) и
// web_jobs.py (воркер ставит running → partial/done/interrupted/failed).
// Раньше карта была скопирована в трёх страницах, и в двух из них не было partial —
// навсегда завершённая джоба рисовалась как «в очереди» (audit-2026-06, P1-4).
// Новый статус добавлять ТОЛЬКО здесь.

/** Человеческая метка и классы бейджа по статусу мультипоиска. */
export const JOB_STATUS = {
  pending:     { label: "в очереди", cls: "border-white/15 bg-white/5 text-muted" },
  running:     { label: "идёт",      cls: "border-ocean/40 bg-ocean/15 text-ocean" },
  done:        { label: "готово",    cls: "border-emerald-400/30 bg-emerald-500/15 text-emerald-200" },
  partial:     { label: "частично",  cls: "border-amber-400/30 bg-amber-400/10 text-amber-300" },
  failed:      { label: "ошибка",    cls: "border-rose-400/30 bg-rose-500/15 text-rose-200" },
  interrupted: { label: "прервано",  cls: "border-amber-400/30 bg-amber-400/10 text-amber-300" },
};

/**
 * Статус джобы → {label, cls}. Неизвестный статус (новый на бэке, битые данные)
 * НЕ маскируем под «в очереди», как делал старый фолбэк ?? STATUS.pending, —
 * показываем сырое значение в нейтральном бейдже, чтобы рассинхрон был виден сразу.
 */
export function jobStatus(status) {
  return JOB_STATUS[status] ?? { label: status || "—", cls: "border-white/15 bg-white/5 text-muted" };
}
