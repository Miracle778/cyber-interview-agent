import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TraceEventInspector } from "./TraceEventInspector";
import { TraceExportDialog } from "./TraceExportDialog";
import type { TraceEventSummary } from "./observabilityTypes";

const event: TraceEventSummary = {
  eventId: "event-1",
  operationId: "model-1",
  eventType: "model.request",
  observedAt: "2026-07-29T06:26:02Z",
  byteLength: 240000,
  sequence: 1,
  bodyState: "available",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TraceEventInspector", () => {
  it("keeps private bodies unloaded while advanced diagnostics is disabled", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={event}
        advancedEnabled={false}
      />,
    );

    expect(screen.getByText("完整内容需开启高级诊断")).toBeInTheDocument();
    expect(screen.getByText(/展示系统实际发送给模型的内容/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("pretty prints a complete paged JSON body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({
        eventId: "event-1",
        eventType: "model.request",
        content: "{\"messages\":[\"hello\"],",
        contentEncoding: "utf-8-json",
        offset: 0,
        nextOffset: 64,
        complete: false,
        sha256: "abc",
        redactionsApplied: true,
      }))
      .mockResolvedValueOnce(Response.json({
        eventId: "event-1",
        eventType: "model.request",
        content: "\"tools\":[{\"name\":\"search\"}],\"temperature\":0.2}",
        contentEncoding: "utf-8-json",
        offset: 64,
        nextOffset: null,
        complete: true,
        sha256: "abc",
        redactionsApplied: true,
      }));

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={event}
        advancedEnabled
      />,
    );

    expect(await screen.findByText("正文超过 200 KB")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /继续加载剩余正文/ }));
    const formatted = await screen.findByLabelText("可读 JSON");
    expect(formatted).toHaveTextContent('"messages"');
    expect(formatted).toHaveTextContent('"tools"');
    expect(formatted).toHaveTextContent('"temperature": 0.2');
    expect(fetchSpy).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=64"),
      expect.anything(),
    );
  });

  it("automatically completes ordinary model responses before formatting them", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({
        eventId: "event-small",
        eventType: "model.response",
        content: "{\"duration_ms\":61872,\"response\":{\"structured_response\":",
        contentEncoding: "utf-8-json",
        offset: 0,
        nextOffset: 65536,
        complete: false,
        sha256: "small",
        redactionsApplied: true,
      }))
      .mockResolvedValueOnce(Response.json({
        eventId: "event-small",
        eventType: "model.response",
        content: "{\"segments\":[{\"display_name\":\"候选人\"}]},\"result\":[]}}",
        contentEncoding: "utf-8-json",
        offset: 65536,
        nextOffset: null,
        complete: true,
        sha256: "small",
        redactionsApplied: true,
      }));

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, eventId: "event-small", eventType: "model.response", byteLength: 102_903 }}
        advancedEnabled
      />,
    );

    expect(await screen.findByRole("heading", { name: "结构化结果" })).toBeInTheDocument();
    expect(screen.getByText("候选人")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /继续加载/ })).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("shows a readable review answer before the raw model request", async () => {
    const content = JSON.stringify({
      provider_model_id: "glm-config-1",
      messages: [{
        type: "human",
        content: "冻结题目：{\"title\":\"MySQL 存储引擎对比\"}\n用户回答：InnoDB 支持事务，MyISAM 不支持事务\n补充回答：默认使用 InnoDB",
      }],
      system_message: {
        type: "system",
        content: "根据冻结题目评价用户回答。",
      },
      model_settings: { temperature: 0.2 },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      eventId: "event-1",
      eventType: "model.request",
      content,
      contentEncoding: "utf-8-json",
      offset: 0,
      nextOffset: null,
      complete: true,
      sha256: "abc",
      redactionsApplied: true,
    }));

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, byteLength: content.length }}
        advancedEnabled
        modelCatalog={{
          "glm-config-1": {
            displayName: "GLM 5.2",
            modelId: "glm-5.2",
            providerName: "火山方舟",
          },
        }}
      />,
    );

    expect(await screen.findByRole("heading", { name: "本次用户回答" })).toBeInTheDocument();
    expect(screen.getByText("InnoDB 支持事务，MyISAM 不支持事务")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "补充回答" })).toBeInTheDocument();
    expect(screen.getByText("默认使用 InnoDB")).toBeInTheDocument();
    expect(screen.getAllByText("MySQL 存储引擎对比", { exact: false })).not.toHaveLength(0);
    expect(screen.getByText("根据冻结题目评价用户回答。")).toBeInTheDocument();
    expect(screen.getByText("GLM 5.2")).toBeInTheDocument();
    expect(screen.getByText(/glm-5\.2/)).toBeInTheDocument();
    expect(screen.getByText(/火山方舟/)).toBeInTheDocument();
    expect(screen.getByText("模型输入上下文").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("系统上下文").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("使用模型与参数").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("原始事件 JSON").closest("details")).not.toHaveAttribute("open");
    expect(
      [...document.querySelectorAll(".trace-model-request > details > summary")]
        .map((item) => item.textContent),
    ).toEqual([
      "使用模型与参数",
      "系统上下文",
      "模型输入上下文",
      "原始事件 JSON",
    ]);
  });

  it("shows the tools available to a model request without implying they were called", async () => {
    const content = JSON.stringify({
      messages: [{ type: "human", content: "这道题哪里答得不好？" }],
      tools: [{
        name: "read_question_analysis",
        description: "Read one question and its current analysis in this retrospective.",
        args: {
          question_id: { type: "string", description: "Current question ID" },
        },
      }, {
        name: "read_source_excerpt",
        description: "Read bounded source excerpts belonging to one current question.",
        args: {},
      }],
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      eventId: "event-tools",
      eventType: "model.request",
      content,
      contentEncoding: "utf-8-json",
      offset: 0,
      nextOffset: null,
      complete: true,
      sha256: "tools",
      redactionsApplied: true,
    }));

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, eventId: "event-tools", byteLength: content.length }}
        advancedEnabled
      />,
    );

    expect(await screen.findByText("本次可用 Tool（2）")).toBeInTheDocument();
    expect(screen.getByText(/不代表已经调用/)).toBeInTheDocument();
    expect(screen.getByText("读取当前题目及分析")).toBeInTheDocument();
    expect(screen.getByText("read_question_analysis")).toBeInTheDocument();
    expect(screen.getByText("读取当前题目的原文片段")).toBeInTheDocument();
    expect(screen.getByText("read_source_excerpt")).toBeInTheDocument();
    expect(screen.getAllByText("查看参数 Schema")[0]?.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("无需参数")).toBeInTheDocument();
  });

  it("shows generic model input as readable content without mislabelling it as a user answer", async () => {
    const escapedQuestions = JSON.stringify([{
      seed_key: "seed-1",
      question_text: "SQLite 出现 database is locked 时应该怎样治理？",
      source_refs: ["source#section-001", "source#section-002"],
    }]).replaceAll("\"", "\\\"");
    const content = JSON.stringify({
      messages: [{
        role: "user",
        content: `题目种子：\n\n${escapedQuestions}\n\n对应来源：source#section-001`,
      }],
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      eventId: "event-1",
      eventType: "model.request",
      content,
      contentEncoding: "utf-8-json",
      offset: 0,
      nextOffset: null,
      complete: true,
      sha256: "abc",
      redactionsApplied: true,
    }));

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, byteLength: content.length }}
        advancedEnabled
      />,
    );

    expect(await screen.findByRole("button", { name: "格式化" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const formatted = screen.getByLabelText("可读 JSON");
    expect(formatted).toHaveTextContent("题目种子：");
    expect(formatted.textContent).toContain("题目种子：\n\n");
    expect(formatted.textContent).not.toContain("题目种子：\\n\\n");
    expect(screen.getByRole("heading", { name: "发送给模型的内容" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "本次用户回答" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "原文" }));
    expect(screen.getByText(content)).toBeInTheDocument();
  });

  it("falls back to raw text and reports copy success and failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      eventId: "event-1",
      eventType: "model.request",
      content: "not-json",
      contentEncoding: "utf-8-json",
      offset: 0,
      complete: true,
      sha256: "abc",
      redactionsApplied: false,
    }));
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("no"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={event}
        advancedEnabled
      />,
    );

    expect(await screen.findByText("正文不是可解析的 JSON，已按原文显示。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制正文" }));
    expect(await screen.findByText("已复制")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制正文" }));
    expect(await screen.findByText("复制失败")).toBeInTheDocument();
  });

  it("renders reasoning only when the provider actually returned it", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({
      eventId: "event-1",
      eventType: "model.response",
      content: JSON.stringify({
        duration_ms: 120,
        response: {
          structured_response: {
            covered_key_points: ["事务"],
            missing_key_points: ["锁机制"],
            follow_up_prompt: "请继续说明锁机制",
            speakers: [{ display_name: "面试官", confidence: 0.8 }],
          },
          result: [{
            type: "ai",
            content: "评价完成",
            usage_metadata: {
              input_tokens: 520,
              output_tokens: 120,
              total_tokens: 640,
            },
          }],
        },
      }),
      contentEncoding: "utf-8-json",
      offset: 0,
      nextOffset: null,
      complete: true,
      sha256: "abc",
      redactionsApplied: true,
      reasoning: { summary: "provider supplied" },
    }));
    const { unmount } = render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, eventType: "model.response" }}
        advancedEnabled
      />,
    );
    expect(await screen.findByRole("heading", { name: "Provider 返回的 reasoning" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "结构化结果" })).toBeInTheDocument();
    expect(screen.getByText("已覆盖关键点")).toBeInTheDocument();
    expect(screen.getByText("事务")).toBeInTheDocument();
    expect(screen.getByText("待完善关键点")).toBeInTheDocument();
    expect(screen.getByText("锁机制")).toBeInTheDocument();
    expect(screen.getByText("事务").closest("li")).toHaveAttribute("data-value-kind", "scalar");
    expect(screen.getByText("面试官").closest("li")).toHaveAttribute("data-value-kind", "record");
    expect(screen.getByText("请继续说明锁机制")).toBeInTheDocument();
    expect(screen.getByText("120 毫秒")).toBeInTheDocument();
    expect(screen.getByText("640")).toBeInTheDocument();
    expect(screen.getByText("原始事件 JSON")).toBeInTheDocument();
    unmount();

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      eventId: "event-2",
      eventType: "model.response",
      content: "{\"structured_response\":{\"score\":3}}",
      contentEncoding: "utf-8-json",
      offset: 0,
      nextOffset: null,
      complete: true,
      sha256: "def",
      redactionsApplied: true,
    }));
    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={{ ...event, eventId: "event-2", eventType: "model.response" }}
        advancedEnabled
      />,
    );
    await screen.findByLabelText("可读 JSON");
    expect(screen.queryByText(/reasoning/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Provider 未返回可展示的思维过程")).not.toBeInTheDocument();
  });

  it("uses dialog semantics for the narrow-screen drawer", () => {
    render(
      <TraceEventInspector
        workspaceId="workspace-1"
        runId="run-1"
        event={event}
        advancedEnabled={false}
        drawer
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog", { name: "事件详情" })).toHaveClass(
      "trace-event-inspector--drawer",
    );
  });
});

describe("TraceExportDialog", () => {
  it("previews privacy scope and shows receipt progress", async () => {
    let resolveExport!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>((resolve) => {
        resolveExport = resolve;
      }),
    );
    render(
      <TraceExportDialog
        workspaceId="workspace-1"
        runId="run-1"
        advancedEnabled
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "导出诊断包" })).toHaveTextContent(
      "可能包含 Prompt、回答、Tool 参数和 Provider 原始响应",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "包含已保存正文" }));
    fireEvent.click(screen.getByRole("button", { name: "生成诊断包" }));
    expect(screen.getByRole("button", { name: "正在生成…" })).toBeDisabled();

    resolveExport(Response.json({
      id: "export-1",
      workspaceId: "workspace-1",
      runId: "run-1",
      status: "completed",
      metadataOnly: false,
      includesBodies: true,
      artifactSha256: "abc",
      errorCode: null,
      createdAt: "2026-07-29T06:30:00Z",
      completedAt: "2026-07-29T06:30:01Z",
    }, { status: 201 }));

    expect(await screen.findByText("诊断包已生成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 ZIP" })).toHaveAttribute(
      "href",
      "/api/agent-observability/exports/export-1?workspaceId=workspace-1",
    );
  });
});
