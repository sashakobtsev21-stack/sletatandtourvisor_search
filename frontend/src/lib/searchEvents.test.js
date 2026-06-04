import { describe, it, expect } from "vitest";
import { progressFloorForLog, isSearchStart, parseProviderDone } from "./searchEvents.js";

describe("progressFloorForLog", () => {
  it("вехи поиска → пол прогресса", () => {
    expect(progressFloorForLog("Проверяю формы площадок (health-check)…")).toBe(10);
    expect(progressFloorForLog("Гейт пройден. Запускаю…")).toBe(20);
    expect(progressFloorForLog("Запускаю поиск на площадках…")).toBe(28);
    expect(progressFloorForLog("search start: providers=...")).toBe(28);
  });
  it("обычная строка → 0", () => {
    expect(progressFloorForLog("какой-то лог")).toBe(0);
    expect(progressFloorForLog("")).toBe(0);
  });
});

describe("isSearchStart", () => {
  it("ловит старт поиска", () => {
    expect(isSearchStart("Запускаю поиск…")).toBe(true);
    expect(isSearchStart("search start: ...")).toBe(true);
    expect(isSearchStart("Гейт пройден")).toBe(false);
  });
});

describe("parseProviderDone", () => {
  it("разбирает «provider X: OK/FAIL»", () => {
    expect(parseProviderDone("provider sletat: OK 5.0s, 12 результатов")).toEqual({ name: "sletat", verdict: "OK" });
    expect(parseProviderDone("provider level: FAIL")).toEqual({ name: "level", verdict: "FAIL" });
  });
  it("не матчит прочее → null", () => {
    expect(parseProviderDone("Гейт пройден")).toBeNull();
    expect(parseProviderDone("")).toBeNull();
    expect(parseProviderDone(null)).toBeNull();
  });
});
