import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { EvaluationLabPage } from "./EvaluationLabPage";


const workspace: WorkspaceConfig = {
  id: "workspace-1",
  displayName: "面试准备",
  workspacePath: "/tmp/interview",
  vaultPath: "/tmp/interview/vault",
};

const run = {
  id: "eval-1",
  workspaceId: "workspace-1",
  executionId: "execution-1",
  evalPackId: "review.v1",
  evalPackVersion: 1,
  trigger: "manual",
  status: "completed",
  frozenInputHash: "a".repeat(64),
  judgeProviderModelId: "model-1",
  errorCode: null,
  createdAt: "2026-07-30T00:00:00Z",
  startedAt: "2026-07-30T00:00:01Z",
  completedAt: "2026-07-30T00:00:02Z",
  dimensions: [
    {
      dimensionId: "correctness",
      source: "judge",
      status: "scored",
      score: 86,
      confidence: 0.82,
      summary: "关键结论有事件证据支持",
      citedEventHashes: ["event-hash-1"],
      citedArtifactHashes: ["artifact-hash-1"],
      risks: ["边界条件证据较少"],
    },
  ],
  deterministicResult: { status: "passed" },
  judgeSummary: {
    confidence: 0.82,
    summary: "整体质量稳定",
    risks: [],
    humanReviewRequired: false,
  },
  judgeTraceRunId: null,
  rawSnapshot: null,
  rawJudgeResult: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/agents/evaluations?executionId=execution-1"]}>
      <QueryClientProvider client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}>
        <EvaluationLabPage workspace={workspace} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EvaluationLabPage", () => {
  it("shows dimension evidence and launches manual Judge", async () => {
    const requests: Array<{ url: string; method: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({ url, method });
      if (url.includes("/feedback")) return Response.json([]);
      if (url.includes("/regression-cases")) return Response.json({ items: [] });
      if (method === "POST" && url.includes("/runs?")) return Response.json(run);
      return Response.json({ items: [run] });
    });
    renderPage();
    expect(await screen.findByText("整体质量稳定")).toBeInTheDocument();
    expect(screen.getByText("86 分")).toBeInTheDocument();
    expect(screen.getByText(/event-has/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "发起 Judge" }));
    await waitFor(() => expect(
      requests.some((request) =>
        request.method === "POST" && request.url.includes("/api/agent-evaluations/runs?")
      ),
    ).toBe(true));
  });

  it("keeps raw Judge data hidden when backend does not disclose it", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/feedback")) return Response.json([]);
      return String(input).includes("/regression-cases")
        ? Response.json({ items: [] })
        : Response.json({ items: [run] });
    });
    renderPage();
    await screen.findByText("整体质量稳定");
    expect(screen.queryByText("高级诊断：Judge 原始输入与输出")).not.toBeInTheDocument();
    expect(screen.queryByText(/cost/i)).not.toBeInTheDocument();
  });
});
