import { describe, it, expect } from "vitest";
import { JOB_STATUS, jobStatus } from "./jobStatus.js";

// Полный набор статусов jobs.status на бэке — src/toursearch/storage.py (схема таблицы jobs)
// и src/toursearch/web_jobs.py (воркер: running → done/partial/failed/interrupted).
// Появился новый статус на бэке → добавить сюда И в JOB_STATUS.
const BACKEND_STATUSES = ["pending", "running", "done", "partial", "failed", "interrupted"];

describe("JOB_STATUS", () => {
  it("покрывает все статусы бэка (label + cls)", () => {
    for (const s of BACKEND_STATUSES) {
      expect(JOB_STATUS[s], `статус «${s}» отсутствует в карте`).toBeDefined();
      expect(JOB_STATUS[s].label).toBeTruthy();
      expect(JOB_STATUS[s].cls).toBeTruthy();
    }
  });

  it("без лишних статусов: карта и бэк синхронны", () => {
    expect(Object.keys(JOB_STATUS).sort()).toEqual([...BACKEND_STATUSES].sort());
  });

  it("partial — «частично», а не «в очереди» (audit-2026-06 P1-4)", () => {
    expect(JOB_STATUS.partial.label).toBe("частично");
  });
});

describe("jobStatus", () => {
  it("известный статус → запись из карты", () => {
    expect(jobStatus("done")).toBe(JOB_STATUS.done);
    expect(jobStatus("partial")).toBe(JOB_STATUS.partial);
  });

  it("неизвестный статус НЕ маскируется под «в очереди» — видно сырое значение", () => {
    const st = jobStatus("какой-то-новый");
    expect(st.label).toBe("какой-то-новый");
    expect(st.label).not.toBe(JOB_STATUS.pending.label);
    expect(st.cls).toBeTruthy();
  });

  it("пустой/отсутствующий статус → прочерк", () => {
    expect(jobStatus(undefined).label).toBe("—");
    expect(jobStatus("").label).toBe("—");
  });
});
