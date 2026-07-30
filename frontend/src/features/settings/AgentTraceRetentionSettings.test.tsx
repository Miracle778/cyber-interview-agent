import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentTraceRetentionSettings } from "./AgentTraceRetentionSettings";


function renderSettings() {
  return render(
    <QueryClientProvider client={new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })}>
      <AgentTraceRetentionSettings workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AgentTraceRetentionSettings", () => {
  it("offers three policies and confirms a metadata-preserving cleanup", async () => {
    let bodyPolicy = "days";
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/cleanup-plans/cleanup-1/confirm")) {
        return Response.json({
          id: "cleanup-1", workspaceId: "workspace-1", status: "completed",
          fileCount: 2, eventCount: 14, totalBytes: 4096,
          protectedActiveRuns: 1, errorCode: null, createdAt: "now",
          completedAt: "now", items: [],
        });
      }
      if (url.includes("/cleanup-plans")) {
        return Response.json({
          id: "cleanup-1", workspaceId: "workspace-1", status: "planned",
          fileCount: 2, eventCount: 14, totalBytes: 4096,
          protectedActiveRuns: 1, errorCode: null, createdAt: "now",
          completedAt: null, items: [],
        });
      }
      if (init?.method === "PUT") {
        bodyPolicy = JSON.parse(String(init.body)).bodyPolicy;
      }
      return Response.json({
        workspaceId: "workspace-1",
        bodyPolicy,
        bodyDays: bodyPolicy === "days" ? 90 : null,
        metadataPolicy: "retain",
        updatedAt: "now",
      });
    });
    renderSettings();
    expect(await screen.findByLabelText(/保留 90 天/)).toBeChecked();
    expect(screen.getByLabelText(/永久保留正文/)).toBeInTheDocument();
    expect(screen.getByLabelText(/仅保留元数据/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/仅保留元数据/));
    await waitFor(() => expect(screen.getByLabelText(/仅保留元数据/)).toBeChecked());
    fireEvent.click(screen.getByRole("button", { name: "预览清理" }));
    expect(await screen.findByText("14")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: "dd" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认清理" }));
    expect(screen.getByRole("dialog", { name: "确认删除 Trace 正文" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认删除正文" }));
    expect(await screen.findByText(/正文已删除/)).toBeInTheDocument();
    expect(requests.some((item) => item.includes("confirm"))).toBe(true);
    expect(document.body.textContent).not.toMatch(/cost|费用/i);
  });

  it("shows a safe partial-failure receipt", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/cleanup-plans")) {
        return Response.json({
          id: "cleanup-1", workspaceId: "workspace-1", status: "partial_failure",
          fileCount: 1, eventCount: 2, totalBytes: 100,
          protectedActiveRuns: 0, errorCode: "trace_cleanup_partial",
          createdAt: "now", completedAt: null, items: [],
        });
      }
      return Response.json({
        workspaceId: "workspace-1", bodyPolicy: "days", bodyDays: 90,
        metadataPolicy: "retain", updatedAt: "now",
      });
    });
    renderSettings();
    await screen.findByLabelText(/保留 90 天/);
    fireEvent.click(screen.getByRole("button", { name: "预览清理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("部分正文未能安全清理");
  });
});
