// AuthProvider — login → refresh → setUser; logout → setUser(null) + navigate
// (порядок refresh ДО navigate — фикс audit-3, чтобы не было артефакта залогиненного
// гостя на гостевом маршруте).
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth.jsx";

beforeEach(() => {
  global.fetch = vi.fn();
  // Hash-router смотрит window.location.hash — выставляем «/» для guest-route.
  window.location.hash = "";
});

function mockMe(payload) {
  // 1-й вызов /api/me и любые последующие — отвечают payload'ом.
  global.fetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
    headers: new Headers({ "content-type": "application/json" }),
  });
}

describe("AuthProvider.refresh", () => {
  it("на старте подтягивает /api/me и кладёт user", async () => {
    mockMe({ mode: "user", username: "alice", role: "admin", permissions: ["users.manage"] });
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    expect(result.current.user.username).toBe("alice");
    expect(result.current.user.role).toBe("admin");
    expect(result.current.loading).toBe(false);
  });

  it("при 401 от /api/me — user остаётся null, loading=false", async () => {
    global.fetch.mockResolvedValue({
      ok: false, status: 401,
      json: async () => ({ error: "no" }),
      headers: new Headers(),
    });
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });
});

describe("AuthProvider.can", () => {
  it("can(perm) проверяет permissions массив", async () => {
    mockMe({
      mode: "user", username: "u", role: "user",
      permissions: ["search.run", "history.view.own"],
    });
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    expect(result.current.can("search.run")).toBe(true);
    expect(result.current.can("users.manage")).toBe(false);
  });
});
