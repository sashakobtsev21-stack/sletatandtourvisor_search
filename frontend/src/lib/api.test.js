import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiFetch, setUnauthorizedHandler } from "./api.js";

describe("apiFetch", () => {
  beforeEach(() => {
    globalThis.document = { cookie: "" };
    globalThis.fetch = vi.fn(async () => ({ status: 200, ok: true }));
    setUnauthorizedHandler(() => {});
  });

  it("GET — credentials include, без X-CSRF-Token", async () => {
    globalThis.document.cookie = "ts_csrf=abc123";
    await apiFetch("/api/runs");
    const [, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.credentials).toBe("include");
    expect(opts.headers.get("X-CSRF-Token")).toBeNull(); // GET — безопасный метод
  });

  it("POST — подставляет X-CSRF-Token из cookie ts_csrf", async () => {
    globalThis.document.cookie = "foo=1; ts_csrf=tok42; bar=2";
    await apiFetch("/search/prepare", { method: "POST" });
    const [, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.headers.get("X-CSRF-Token")).toBe("tok42");
  });

  it("POST без cookie ts_csrf — заголовок не ставится (локальный режим)", async () => {
    await apiFetch("/tests/prepare", { method: "POST" });
    const [, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.headers.get("X-CSRF-Token")).toBeNull();
  });

  it("401 → дёргает обработчик; на /api/login — НЕ дёргает", async () => {
    const onUnauth = vi.fn();
    setUnauthorizedHandler(onUnauth);
    globalThis.fetch = vi.fn(async () => ({ status: 401, ok: false }));

    await apiFetch("/api/runs");
    expect(onUnauth).toHaveBeenCalledTimes(1);

    onUnauth.mockClear();
    await apiFetch("/api/login", { method: "POST" });
    expect(onUnauth).not.toHaveBeenCalled(); // вход 401 — это просто «неверный пароль»
  });
});
