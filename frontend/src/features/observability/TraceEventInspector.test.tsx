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
    expect(screen.getByText(/仅展示 Provider 实际返回的数据/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows labelled request sections and warns before paging a large body", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "继续加载" }));
    expect(await screen.findByRole("heading", { name: "请求消息" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "工具定义" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "模型参数" })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenLastCalledWith(
      expect.stringContaining("offset=64"),
      expect.anything(),
    );
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
      content: "{\"duration_ms\":120,\"response\":{\"structured_response\":{\"score\":4},\"result\":\"raw\"}}",
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
    expect(screen.getByRole("heading", { name: "结构化响应" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "原始响应" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "响应元数据" })).toBeInTheDocument();
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
    await screen.findByRole("heading", { name: "结构化响应" });
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
