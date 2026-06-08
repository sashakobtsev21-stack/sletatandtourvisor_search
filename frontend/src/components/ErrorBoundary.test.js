// Логический тест ErrorBoundary (без рендера — @testing-library/react не подключён).
// Проверяем state-машину: getDerivedStateFromError, reset, сброс на смене resetKey.
import { describe, it, expect, vi } from "vitest";
import ErrorBoundary from "./ErrorBoundary.jsx";

describe("ErrorBoundary state-машина", () => {
  it("getDerivedStateFromError возвращает {error}", () => {
    const e = new Error("boom");
    expect(ErrorBoundary.getDerivedStateFromError(e)).toEqual({ error: e });
  });

  it("componentDidUpdate сбрасывает ошибку при смене resetKey", () => {
    const eb = Object.create(ErrorBoundary.prototype);
    eb.state = { error: new Error("x") };
    eb.props = { resetKey: "/new" };
    eb.setState = vi.fn();
    eb.componentDidUpdate({ resetKey: "/old" });
    expect(eb.setState).toHaveBeenCalledWith({ error: null });
  });

  it("componentDidUpdate НЕ трогает state, когда resetKey тот же", () => {
    const eb = Object.create(ErrorBoundary.prototype);
    eb.state = { error: new Error("x") };
    eb.props = { resetKey: "/same" };
    eb.setState = vi.fn();
    eb.componentDidUpdate({ resetKey: "/same" });
    expect(eb.setState).not.toHaveBeenCalled();
  });

  it("componentDidUpdate без активной ошибки тоже не трогает state", () => {
    const eb = Object.create(ErrorBoundary.prototype);
    eb.state = { error: null };
    eb.props = { resetKey: "/new" };
    eb.setState = vi.fn();
    eb.componentDidUpdate({ resetKey: "/old" });
    expect(eb.setState).not.toHaveBeenCalled();
  });
});
