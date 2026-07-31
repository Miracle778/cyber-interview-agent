import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiGet", () => {
  it("returns json for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }))));
    await expect(apiGet<{ status: string }>("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it.each([
    "https://attacker.example/collect",
    "//attacker.example/collect",
    "/api/../admin",
    "/not-api/health",
  ])("rejects paths outside the same-origin API boundary: %s", async (path) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet(path)).rejects.toMatchObject({
      code: "invalid_api_path",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("throws ApiError for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "bad", message: "坏请求" }), { status: 400 })));
    await expect(apiGet("/api/fail")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPost", () => {
  it("posts json and returns the response", async () => {
    const fetchMock = vi.fn(async (_input: unknown, init?: RequestInit) =>
      new Response(JSON.stringify({ id: "1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiPost<{ x: number }, { id: string }>("/api/x", { x: 1 })).resolves.toEqual({ id: "1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/x", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/x",
      expect.objectContaining({ body: JSON.stringify({ x: 1 }) }),
    );
  });
});

describe("apiPatch", () => {
  it("sends a PATCH with json body and returns the parsed response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: "p1", name: "Patched" })));
    vi.stubGlobal("fetch", fetchMock);
    await apiPatch<{ name: string }, { id: string }>("/api/settings/providers/p1", { name: "Patched" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/providers/p1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "Patched" }) }),
    );
  });

  it("converts error responses to ApiError with code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "resource_in_use", message: "仍被绑定" }), { status: 409 })));
    await expect(apiPatch("/api/x", { a: 1 })).rejects.toMatchObject({ code: "resource_in_use", message: "仍被绑定" });
  });
});

describe("apiPut", () => {
  it("sends a PUT with json body and returns the parsed response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    await apiPut<{ a: number }, { ok: boolean }>("/api/x", { a: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/x",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ a: 1 }) }),
    );
  });
});

describe("apiDelete", () => {
  it("resolves with void on 204 No Content without parsing a body", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiDelete("/api/settings/providers/p1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/providers/p1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("converts 409 conflict to ApiError with code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "resource_in_use", message: "占用" }), { status: 409 })));
    await expect(apiDelete("/api/x")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiUpload", () => {
  it("sends multipart data without forcing a JSON content type and keeps abort/error behavior", async () => {
    const fetchMock = vi.fn(async (_input: unknown, init?: RequestInit) => {
      expect(init?.body).toBeInstanceOf(FormData);
      expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
      return new Response(JSON.stringify({ versionId: "version-1" }), { status: 202 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const formData = new FormData();
    formData.set("file", new File(["resume"], "resume.md", { type: "text/markdown" }));

    await expect(apiUpload<{ versionId: string }>("/api/profile", formData, {
      signal: controller.signal,
      headers: { "Idempotency-Key": "upload-test-key" },
    })).resolves.toEqual({ versionId: "version-1" });
    expect(fetchMock).toHaveBeenCalledWith("/api/profile", expect.objectContaining({
      method: "POST",
      signal: controller.signal,
    }));

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "profile_upload_too_large", message: "文件过大" }), { status: 413 })));
    await expect(apiUpload("/api/profile", formData)).rejects.toMatchObject({ code: "profile_upload_too_large", message: "文件过大" });
  });
});
