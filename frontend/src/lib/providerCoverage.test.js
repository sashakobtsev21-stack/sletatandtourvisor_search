import { describe, it, expect } from "vitest";
import { supportsCity, supportsCountry, supportsMode, supportsOperatorFilter, incompatReasons, caveatOf } from "./providerCoverage.js";

const coverage = {
  sletat:    { modes: ["tours", "hotels"], departure_cities: "all", countries: "all", operator_filter: true, caveat: "" },
  travelata: { modes: ["tours"], departure_cities: ["Москва", "СПб"], countries: ["Турция"], operator_filter: true, caveat: "Только туры." },
  ostrovok:  { modes: ["hotels"], departure_cities: "all", countries: "all", operator_filter: false, caveat: "Отели." },
};

describe("supportsCity", () => {
  it("`all` → любой город", () => {
    expect(supportsCity(coverage, "sletat", "Алматы")).toBe(true);
  });
  it("список → только из whitelist", () => {
    expect(supportsCity(coverage, "travelata", "Москва")).toBe(true);
    expect(supportsCity(coverage, "travelata", "Тбилиси")).toBe(false);
  });
  it("неизвестный провайдер → true (нет ограничений)", () => {
    expect(supportsCity(coverage, "unknown", "Любой")).toBe(true);
  });
});

describe("supportsCountry / supportsMode", () => {
  it("travelata: Турция да, Грузия нет", () => {
    expect(supportsCountry(coverage, "travelata", "Турция")).toBe(true);
    expect(supportsCountry(coverage, "travelata", "Грузия")).toBe(false);
  });
  it("ostrovok: hotels да, tours нет", () => {
    expect(supportsMode(coverage, "ostrovok", "hotels")).toBe(true);
    expect(supportsMode(coverage, "ostrovok", "tours")).toBe(false);
  });
});

describe("incompatReasons", () => {
  it("полностью совместимая площадка → пустой массив", () => {
    expect(incompatReasons(coverage, "sletat", { city: "Москва", country: "Турция", mode: "tours" })).toEqual([]);
  });
  it("travelata + Грузия → список причин с упоминанием страны", () => {
    const r = incompatReasons(coverage, "travelata", { city: "Москва", country: "Грузия", mode: "tours" });
    expect(r.some((s) => s.includes("Грузия"))).toBe(true);
  });
  it("ostrovok + tours → причина mode", () => {
    const r = incompatReasons(coverage, "ostrovok", { city: "Москва", country: "Турция", mode: "tours" });
    expect(r.some((s) => s.includes("tours") || s.includes("режим"))).toBe(true);
  });
});

describe("supportsOperatorFilter", () => {
  it("ostrovok = false (отели без понятия 'туроператор')", () => {
    expect(supportsOperatorFilter(coverage, "ostrovok")).toBe(false);
  });
  it("sletat/travelata = true", () => {
    expect(supportsOperatorFilter(coverage, "sletat")).toBe(true);
    expect(supportsOperatorFilter(coverage, "travelata")).toBe(true);
  });
  it("unknown provider = true (нет данных → считаем поддерживает)", () => {
    expect(supportsOperatorFilter(coverage, "unknown")).toBe(true);
  });
});

describe("incompatReasons + operators", () => {
  it("ostrovok + выбранные операторы → причина про оператора", () => {
    const r = incompatReasons(coverage, "ostrovok", {
      mode: "hotels", operators: ["Anex"],
    });
    expect(r.some((s) => s.includes("туроператор"))).toBe(true);
  });
  it("ostrovok без operators → причина про оператора НЕ появляется", () => {
    const r = incompatReasons(coverage, "ostrovok", { mode: "hotels", operators: [] });
    expect(r.some((s) => s.includes("туроператор"))).toBe(false);
  });
});

describe("caveatOf", () => {
  it("возвращает текст-подсказку или пустую строку", () => {
    expect(caveatOf(coverage, "travelata")).toBe("Только туры.");
    expect(caveatOf(coverage, "unknown")).toBe("");
  });
});
