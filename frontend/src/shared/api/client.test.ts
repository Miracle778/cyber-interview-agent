import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiGet", () => {
  it("returns json for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }))));
    await expect(apiGet<{ status: string }>("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("throws ApiError for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "bad", message: "坏请求" }), { status: 400 })));
    await expect(apiGet("/api/fail")).rejects.toBeInstanceOf(ApiError);
  });
});
