import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiFetch, setUnauthorizedHandler } from "./api.js";

// fetch-мок, возвращающий цепочку ответов по очереди.
function mockResponses(...responses) {
  let i = 0;
  return vi.fn(async () => {
    const next = responses[Math.min(i, responses.length - 1)];
    i++;
    if (next instanceof Error) throw next;
    const { status = 200, retryAfter } = next;
    return {
      status,
      ok: status < 400,
      headers: { get: (h) => (h.toLowerCase() === "retry-after" ? retryAfter ?? null : null) },
    };
  });
}

describe("apiFetch", () => {
  beforeEach(() => {
    globalThis.document = { cookie: "" };
    globalThis.fetch = vi.fn(async () => ({
      status: 200, ok: true, headers: { get: () => null },
    }));
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
    globalThis.fetch = vi.fn(async () => ({
      status: 401, ok: false, headers: { get: () => null },
    }));

    await apiFetch("/api/runs");
    expect(onUnauth).toHaveBeenCalledTimes(1);

    onUnauth.mockClear();
    await apiFetch("/api/login", { method: "POST" });
    expect(onUnauth).not.toHaveBeenCalled(); // вход 401 — это просто «неверный пароль»
  });
});

// --------------------------- P2-4: retry / timeout / abort ---------------------------

describe("apiFetch retry/timeout", () => {
  beforeEach(() => {
    globalThis.document = { cookie: "" };
    setUnauthorizedHandler(() => {});
  });

  it("GET с 503 ретраится дважды и возвращает финальный 200", async () => {
    globalThis.fetch = mockResponses(
      { status: 503 }, { status: 503 }, { status: 200 },
    );
    const r = await apiFetch("/api/runs");
    expect(r.status).toBe(200);
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });

  it("GET с 429 + Retry-After: 0 ретраится сразу", async () => {
    globalThis.fetch = mockResponses(
      { status: 429, retryAfter: "0" }, { status: 200 },
    );
    const r = await apiFetch("/api/runs");
    expect(r.status).toBe(200);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("POST по умолчанию НЕ ретраится на 503 (риск двойного списания)", async () => {
    globalThis.fetch = mockResponses({ status: 503 }, { status: 200 });
    const r = await apiFetch("/search/prepare", { method: "POST" });
    expect(r.status).toBe(503);                              // первый ответ, без ретрая
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("POST с явным retry:true — ретраится", async () => {
    globalThis.fetch = mockResponses({ status: 503 }, { status: 200 });
    const r = await apiFetch("/api/idempotent", { method: "POST", retry: true });
    expect(r.status).toBe(200);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("после MAX_RETRIES возвращает последний ответ (а не throw)", async () => {
    globalThis.fetch = mockResponses(
      { status: 503 }, { status: 503 }, { status: 503 }, { status: 503 },
    );
    const r = await apiFetch("/api/runs");
    expect(r.status).toBe(503);                              // не успело перейти в 200
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);       // 1 первичная + 2 ретрая
  });

  it("таймаут (TimeoutError) НЕ ретраится, несмотря на GET (audit P2)", async () => {
    // Иначе зависший сервер держал бы запрос до MAX_RETRIES×timeoutMs (~90с).
    globalThis.fetch = vi.fn(async () => {
      throw new DOMException("timeout", "TimeoutError");
    });
    await expect(apiFetch("/api/runs")).rejects.toThrow();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("внешний AbortSignal отменяет до завершения", async () => {
    // fetch принимает signal — реалистично пробрасываем abort через ошибку.
    globalThis.fetch = vi.fn(async (_url, opts) => {
      return new Promise((_, reject) => {
        opts.signal.addEventListener("abort",
          () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    const ctrl = new AbortController();
    const promise = apiFetch("/api/runs", { signal: ctrl.signal });
    ctrl.abort();
    await expect(promise).rejects.toThrow();
  });
});
