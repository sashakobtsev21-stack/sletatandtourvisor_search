// Смоук-рендер SearchForm: форма монтируется без падения.
// Этот тест ловит класс багов «висячая ссылка на удалённую переменную» (например, после
// выпила batch-режима остался `batch` в JSX → ReferenceError при рендере) — build и
// другие тесты такое НЕ ловят, т.к. это рантайм-ошибка, а компонент рендерится только в
// реальном приложении (audit P2-review: именно так blocker и проскочил).
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LazyMotion, domAnimation } from "framer-motion";
import SearchForm from "./SearchForm.jsx";

// Без бэкенда useRefData падает на фолбэк-константы — форме хватает их для рендера.
vi.mock("../lib/api.js", () => ({
  apiFetch: vi.fn(() => Promise.reject(new Error("no backend in test"))),
}));

function renderForm(props = {}) {
  return render(
    <LazyMotion features={domAnimation}>
      <SearchForm onSubmit={() => {}} {...props} />
    </LazyMotion>,
  );
}

describe("SearchForm", () => {
  it("рендерится без ошибок (одиночный поиск)", () => {
    renderForm();
    expect(screen.getByText("Параметры поиска")).toBeInTheDocument();
    expect(screen.getByText("Куда?")).toBeInTheDocument();
    expect(screen.getByText("Туроператоры")).toBeInTheDocument();
  });

  it("кнопка сабмита — «Сравнить» (не batch-вариант)", () => {
    renderForm();
    expect(screen.getByText("Сравнить")).toBeInTheDocument();
  });
});
