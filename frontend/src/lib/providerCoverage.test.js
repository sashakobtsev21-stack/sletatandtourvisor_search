import { describe, it, expect } from "vitest";
import { supportsCity, supportsCountry, supportsMode, incompatReasons, caveatOf } from "./providerCoverage.js";

const coverage = {
  sletat:    { modes: ["tours", "hotels"], departure_cities: "all", countries: "all", caveat: "" },
  travelata: { modes: ["tours"], departure_cities: ["Москва", "СПб"], countries: ["Турция"], caveat: "Только туры." },
  ostrovok:  { modes: ["hotels"], departure_cities: "all", countries: "all", caveat: "Отели." },
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

describe("caveatOf", () => {
  it("возвращает текст-подсказку или пустую строку", () => {
    expect(caveatOf(coverage, "travelata")).toBe("Только туры.");
    expect(caveatOf(coverage, "unknown")).toBe("");
  });
});
