// Передача готового отчёта прогона со страницы поиска на страницу результатов —
// для ГОСТЯ, у которого нет доступа к защищённому /api/runs/{id}. Бэкенд кладёт отчёт
// в событие SSE `done`, страница поиска складывает его сюда, ResultsPage забирает один
// раз по runId (как repeatStore). У залогиненных отчёт не передаётся — они тянут /api/runs.
let pending = null; // { runId, data } | null

export const putResult = (runId, data) => { pending = { runId, data }; };
export const takeResult = (runId) => {
  if (pending && pending.runId === runId) {
    const data = pending.data;
    pending = null;
    return data;
  }
  return null;
};
