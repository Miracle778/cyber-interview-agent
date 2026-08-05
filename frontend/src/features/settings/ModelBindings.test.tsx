import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelBindings } from "./ModelBindings";

const roles = {
  question_generation: "m1",
  answer_evaluation: "m1",
  report_summarization: "m1",
  agent_chat: "m1",
  profile_extraction: "m1",
  profile_assessment: "m1",
  job_analysis: "m1",
  project_deep_dive: "m1",
  retrospective_analysis: "m1",
  retrospective_chat: "m1",
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
      maxInputTokens: 128000,
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
      maxInputTokens: 128000,
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
  it("loads ten roles and saves a complete binding payload", async () => {
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

    expect(await screen.findByLabelText("题目生成")).toHaveValue("m1");
    expect(screen.getByLabelText("回答评估")).toHaveValue("m1");
    expect(screen.getByLabelText("复习总结")).toHaveValue("m1");
    expect(screen.getByLabelText("通用对话")).toHaveValue("m1");
    expect(screen.getByLabelText("简历信息整理")).toHaveValue("m1");
    expect(screen.getByLabelText("个人资料分析")).toHaveValue("m1");
    expect(screen.getByLabelText("岗位分析")).toHaveValue("m1");
    expect(screen.getByLabelText("项目深挖")).toHaveValue("m1");
    expect(screen.getByLabelText("面试复盘分析")).toHaveValue("m1");
    expect(screen.getByLabelText("面试复盘对话")).toHaveValue("m1");
    expect(screen.getByText("10/10 已配置")).toBeVisible();

    fireEvent.change(screen.getByLabelText("通用对话"), {
      target: { value: "m2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

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
    expect(screen.getByRole("button", { name: "保存配置" })).toBeDisabled();
  });
});
