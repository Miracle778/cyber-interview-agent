import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../shared/api/client";
import { InterviewRetrospectivePage } from "./InterviewRetrospectivePage";

const api = vi.hoisted(() => ({
  listRetrospectives: vi.fn(),
  listJobTargets: vi.fn(),
  getCleanup: vi.fn(),
  getCurrentCleanup: vi.fn(),
  getSourceVersion: vi.fn(),
  createRetrospective: vi.fn(),
  createJobTarget: vi.fn(),
  addSourceVersion: vi.fn(),
  startCleanup: vi.fn(),
  updateSegments: vi.fn(),
  confirmCleanup: vi.fn(),
  stopCleanup: vi.fn(),
  resumeCleanup: vi.fn(),
  getAnalysisReport: vi.fn(),
  startAnalysis: vi.fn(),
  stopAnalysis: vi.fn(),
  resumeAnalysis: vi.fn(),
  retryAnalysis: vi.fn(),
  decideQuestion: vi.fn(),
  listCandidates: vi.fn(),
  decideCandidate: vi.fn(),
  batchDecideCandidates: vi.fn(),
  listActions: vi.fn(),
  decideAction: vi.fn(),
  createPublicationDraft: vi.fn(),
}));

vi.mock("./retrospectiveApi", () => api);
vi.mock("../jobTargets/jobTargetApi", () => ({
  listJobTargets: api.listJobTargets,
  createJobTarget: api.createJobTarget,
}));

const workspace = {
  id: "w1",
  workspacePath: "/workspace",
  vaultPath: "/vault",
};

function renderPage(route = "/retrospectives") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <InterviewRetrospectivePage workspace={workspace} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("InterviewRetrospectivePage", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    api.listJobTargets.mockResolvedValue([
      {
        id: "target-1",
        workspaceId: "w1",
        companyName: "星河科技",
        roleName: "后端工程师",
        seniority: "3-5 年",
        lifecycleStatus: "active",
        version: 1,
      },
    ]);
    api.listRetrospectives.mockResolvedValue([
      {
        id: "retro-1",
        workspaceId: "w1",
        jobTargetId: "target-1",
        title: "星河科技后端一面",
        roundLabel: "一面",
        interviewDate: "2026-08-01",
        outcome: "pending",
        note: "",
        lifecycleStatus: "active",
        activeSourceVersionId: "source-1",
        activeCleanupVersionId: null,
        activeAnalysisRunId: null,
        version: 1,
        createdAt: "2026-08-01 00:00:00",
        updatedAt: "2026-08-01 01:00:00",
      },
    ]);
    api.getCurrentCleanup.mockResolvedValue(null);
    api.getCleanup.mockResolvedValue(null);
    api.getAnalysisReport.mockResolvedValue(null);
    api.listCandidates.mockResolvedValue([]);
    api.listActions.mockResolvedValue([]);
  });

  it("keeps lifecycle tabs visible and applies a target deep link", async () => {
    renderPage("/retrospectives?jobTargetId=target-1");

    expect(await screen.findByRole("heading", { name: "面试复盘" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /进行中/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /已归档/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /回收站/ })).toBeVisible();
    await screen.findByRole("option", { name: "星河科技 / 后端工程师" });
    expect(screen.getByLabelText("求职目标")).toHaveValue("target-1");
    expect(screen.getAllByText("星河科技后端一面")[0]).toBeVisible();
    expect(screen.getAllByText("2026/08/01")[0]).toBeVisible();
  });

  it("restores cleanup progress from the URL and refreshes after a version conflict", async () => {
    api.getCleanup.mockResolvedValue({
      id: "cleanup-1",
      retrospectiveId: "retro-1",
      sourceVersionId: "source-1",
      ordinal: 1,
      executionId: "execution-1",
      status: "review_pending",
      stage: "review_pending",
      controlIntent: null,
      confirmedAt: null,
      version: 3,
      createdAt: "2026-08-01 00:00:00",
      updatedAt: "2026-08-01 00:00:04",
      segments: [{
        id: "segment-1",
        ordinal: 1,
        speakerRole: "unknown",
        rawSpeakerLabel: null,
        displayName: "待确认",
        body: "请介绍一下缓存治理。",
        sourceStart: 0,
        sourceEnd: 11,
        confidence: 0.5,
        uncertaintyReason: "说话人不明确",
        ignored: false,
        version: 1,
      }],
    });
    api.updateSegments.mockRejectedValue(
      new ApiError("retrospective_version_conflict", "整理版本已更新"),
    );

    renderPage("/retrospectives?retrospectiveId=retro-1&cleanupId=cleanup-1");
    expect(await screen.findByText("1 段需要确认")).toBeVisible();
    expect(api.getCleanup).toHaveBeenCalledWith("w1", "retro-1", "cleanup-1", expect.any(AbortSignal));
    fireEvent.change(screen.getByLabelText("第 1 段说话人"), { target: { value: "candidate" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("已为你重新载入最新版本");
    await waitFor(() => expect(api.getCleanup).toHaveBeenCalledTimes(2));
  });

  it("reopens the latest unconfirmed cleanup after returning from navigation", async () => {
    const currentCleanup = {
      id: "cleanup-current",
      retrospectiveId: "retro-1",
      sourceVersionId: "source-1",
      ordinal: 1,
      executionId: "execution-current",
      status: "running",
      stage: "cleanup",
      controlIntent: null,
      confirmedAt: null,
      version: 1,
      createdAt: "2026-08-01 00:00:00",
      updatedAt: "2026-08-01 00:00:01",
      segments: [],
    };
    api.getCurrentCleanup.mockResolvedValue(currentCleanup);
    api.getCleanup.mockResolvedValue(currentCleanup);

    renderPage("/retrospectives");

    expect(await screen.findByText("刷新或离开不会丢失已完成结果。")).toBeVisible();
    expect(api.getCurrentCleanup).toHaveBeenCalledWith("w1", "retro-1", expect.any(AbortSignal));
    expect(api.getCleanup).toHaveBeenCalledWith("w1", "retro-1", "cleanup-current", expect.any(AbortSignal));
  });

  it("opens the failed question first and keeps completed results visible while analysis runs", async () => {
    api.listRetrospectives.mockResolvedValue([{
      id: "retro-1", workspaceId: "w1", jobTargetId: "target-1", title: "星河科技后端一面", roundLabel: "一面", interviewDate: "2026-08-01", outcome: "pending", note: "", lifecycleStatus: "active", activeSourceVersionId: "source-1", activeCleanupVersionId: "cleanup-1", activeAnalysisRunId: "run-1", version: 2, createdAt: "now", updatedAt: "now",
    }]);
    api.getAnalysisReport.mockResolvedValue({
      analysisRun: { id: "run-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", executionId: "execution-1", retryOfAnalysisRunId: null, status: "running", stage: "question_analysis", controlIntent: null, completedItems: 1, totalItems: 3, currentWorkKey: "question_analysis:q-2", cumulativeElapsedMs: 2_000, latestProgressAt: "now", summary: null, version: 2, createdAt: "now", updatedAt: "now" },
      questions: [
        { id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "project", origin: "original", questionText: "已经完成的问题", questionSegmentIds: [], answerSegmentIds: [], inferenceBasis: "", confidence: .9, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" },
        { id: "q-2", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 2, questionKind: "system", origin: "original", questionText: "分析失败的问题", questionSegmentIds: [], answerSegmentIds: [], inferenceBasis: "", confidence: .9, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" },
      ],
      analyses: [{ id: "a-1", analysisRunId: "run-1", questionUnitId: "q-1", verdict: "strong", strengths: [{ summary: "结构清晰", evidenceSegmentIds: [] }], improvements: [], omissions: [], gaps: [], evidenceLevel: "direct", confidence: .9, improvementOutline: [], suggestedAnswer: "", sourceExcerpt: "", sourceAvailable: true, resultStatus: "completed", version: 1 }],
      items: [
        { id: "i-1", questionUnitId: "q-1", workKey: "question_analysis:q-1", status: "completed", attemptCount: 1, lastErrorCode: null, updatedAt: "now" },
        { id: "i-2", questionUnitId: "q-2", workKey: "question_analysis:q-2", status: "retryable", attemptCount: 1, lastErrorCode: "provider_timeout", updatedAt: "now" },
      ],
      summary: {},
    });

    renderPage("/retrospectives?retrospectiveId=retro-1");

    expect(await screen.findByRole("heading", { name: "分析失败的问题" })).toBeVisible();
    expect(screen.getByText("这道题分析失败")).toBeVisible();
    expect(screen.getByRole("button", { name: /已经完成的问题/ })).toBeVisible();
    expect(screen.queryByText(/总分/)).not.toBeInTheDocument();
  });
});
