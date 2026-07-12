import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelBindings } from "./ModelBindings";

const roles = {
  question_generation: "m1",
  answer_evaluation: "m1",
  report_summarization: "m1",
  agent_chat: "m1",
};

const provider = {
  id: "p1",
  name: "Provider",
  apiFormat: "openai-compatible",
  baseUrl: "https://example.test/v1",
  secretSource: "keyring",
  hasSecret: true,
  enabled: true,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-10T00:00:00Z",
  models: [
    {
      id: "m1",
      providerId: "p1",
      modelId: "model-a",
      displayName: "Model A",
      enabled: true,
      connectivityStatus: "ok",
      lastTestedAt: null,
      lastErrorCode: null,
      lastLatencyMs: null,
    },
    {
      id: "m2",
      providerId: "p1",
      modelId: "model-b",
      displayName: "Model B",
      enabled: true,
      connectivityStatus: "unknown",
      lastTestedAt: null,
      lastErrorCode: null,
      lastLatencyMs: null,
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ModelBindings", () => {
  it("loads four roles and saves a complete binding payload", async () => {
    let putBody: unknown;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      const method = init?.method ?? "GET";
      if (url === "/api/settings/providers") {
        return Response.json([provider]);
      }
      if (url.endsWith("/model-bindings") && method === "GET") {
        return Response.json({ workspaceId: "w1", bindings: roles });
      }
      if (url.endsWith("/model-bindings") && method === "PUT") {
        putBody = JSON.parse(init?.body as string);
        return Response.json({ workspaceId: "w1", ...(putBody as object) });
      }
      return Response.json({ code: "unexpected", message: url }, { status: 500 });
    });

    const onBindingsChanged = vi.fn();
    render(<ModelBindings workspaceId="w1" onBindingsChanged={onBindingsChanged} />);

    expect(await screen.findByLabelText("题目生成模型")).toHaveValue("m1");
    expect(screen.getByLabelText("回答评估模型")).toHaveValue("m1");
    expect(screen.getByLabelText("报告总结模型")).toHaveValue("m1");
    expect(screen.getByLabelText("Agent 对话模型")).toHaveValue("m1");

    fireEvent.change(screen.getByLabelText("Agent 对话模型"), {
      target: { value: "m2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存模型绑定" }));

    await waitFor(() =>
      expect(putBody).toEqual({
        bindings: { ...roles, agent_chat: "m2" },
      }),
    );
    expect(onBindingsChanged).toHaveBeenCalledTimes(1);
  });

  it("shows a visible validation error when no enabled model is available", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url === "/api/settings/providers") {
        return Response.json([]);
      }
      return Response.json({ workspaceId: "w1", bindings: {} });
    });

    render(<ModelBindings workspaceId="w1" />);

    expect(await screen.findByText("没有可用于绑定的模型")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存模型绑定" })).toBeDisabled();
  });
});
