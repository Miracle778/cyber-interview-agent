import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProviderManager } from "./ProviderManager";

const JSON_HEADERS = { "Content-Type": "application/json" };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function providerResource(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "p1",
    name: "P",
    apiFormat: "openai-compatible",
    baseUrl: "https://example.test/v1",
    secretSource: "keyring",
    hasSecret: true,
    enabled: true,
    createdAt: "2026-07-10T00:00:00Z",
    updatedAt: "2026-07-10T00:00:00Z",
    models: [] as unknown[],
    ...overrides,
  };
}

function modelResource(modelId: string, displayName: string, id: string, status = "unknown") {
  return {
    id,
    providerId: "p1",
    modelId,
    displayName,
    enabled: true,
    connectivityStatus: status,
    lastTestedAt: null,
    lastErrorCode: null,
    lastLatencyMs: null,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProviderManager", () => {
  it("creates a provider, adds two models, tests one, and never leaks the api key", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      const method = ((init?.method as string) ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(init.body as string) : {};

      if (url === "/api/settings/providers" && method === "GET") {
        return jsonResponse([]);
      }
      if (url === "/api/settings/providers" && method === "POST") {
        return jsonResponse(providerResource({ name: body.name, baseUrl: body.baseUrl }), 201);
      }
      if (url.startsWith("/api/settings/providers/") && url.endsWith("/models") && method === "POST") {
        const id = body.modelId === "model-a" ? "m1" : "m2";
        return jsonResponse(modelResource(body.modelId, body.displayName, id), 201);
      }
      if (url.startsWith("/api/settings/provider-models/") && url.endsWith("/test") && method === "POST") {
        const id = url.split("/")[4];
        const base = id === "m1" ? modelResource("model-a", "Model A", "m1") : modelResource("model-b", "Model B", "m2");
        return jsonResponse({ ...base, connectivityStatus: "auth_failed", lastTestedAt: "t", lastErrorCode: "auth_failed", lastLatencyMs: 12 });
      }
      return jsonResponse({ code: "api_error", message: `unexpected ${method} ${url}` }, 500);
    });

    render(<ProviderManager />);

    await waitFor(() => expect(screen.getByRole("button", { name: "添加 Provider" })).toBeEnabled());

    fireEvent.change(screen.getByLabelText("Provider 名称"), { target: { value: "P" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://example.test/v1" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "添加 Provider" }));

    await screen.findByText("P");

    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "model-a" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Model A" } });
    fireEvent.click(screen.getByRole("button", { name: "添加模型" }));
    await screen.findByText("model-a");

    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "model-b" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Model B" } });
    fireEvent.click(screen.getByRole("button", { name: "添加模型" }));
    await screen.findByText("model-b");

    fireEvent.click(screen.getByRole("button", { name: "测试模型 model-a" }));

    expect(await screen.findByText("认证失败")).toBeInTheDocument();

    // API key must never appear in the rendered DOM (text, content, or input value)
    expect(screen.queryByText(/sk-test-secret/)).toBeNull();
    expect(screen.queryByDisplayValue("sk-test-secret")).toBeNull();
    expect(document.body.textContent ?? "").not.toContain("sk-test-secret");
  });

  it("shows in-use details and unbind advice when deleting a bound provider", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      const method = ((init?.method as string) ?? "GET").toUpperCase();
      if (url === "/api/settings/providers" && method === "GET") {
        return jsonResponse([providerResource({ models: [modelResource("model-a", "Model A", "m1")] })]);
      }
      if (url === "/api/settings/providers/p1" && method === "DELETE") {
        return jsonResponse({ code: "resource_in_use", message: "Provider P 仍被 1 个工作区绑定" }, 409);
      }
      return jsonResponse({ code: "api_error", message: "unexpected" }, 500);
    });

    render(<ProviderManager />);
    await screen.findByText("P");

    fireEvent.click(screen.getByRole("button", { name: "删除 Provider P" }));

    expect(await screen.findByText(/仍被 1 个工作区绑定/)).toBeInTheDocument();
    expect(screen.getByText(/解除.*绑定/)).toBeInTheDocument();
    // provider is retained (not removed) on conflict
    expect(screen.getByText("P")).toBeInTheDocument();
  });
});
