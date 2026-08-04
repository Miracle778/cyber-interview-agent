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
  clearSourceVersion: vi.fn(),
  transitionRetrospective: vi.fn(),
  getRetrospectiveDeletionImpact: vi.fn(),
  permanentlyDeleteRetrospective: vi.fn(),
  createRetrospectiveSearch: vi.fn(),
  listRetrospectiveSearches: vi.fn(),
  getRetrospectiveSearch: vi.fn(),
  listRetrospectiveSearchResults: vi.fn(),
  summarizeRetrospectiveSearch: vi.fn(),
  createRetrospectiveSearchReport: vi.fn(),
  listRetrospectiveSearchReports: vi.fn(),
  updateRetrospectiveSearchReport: vi.fn(),
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
    api.listRetrospectives.mockImplementation((_workspaceId, filters) => Promise.resolve(
      filters.lifecycle === "active" ? [{
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
        activeSourceAvailable: true,
        activeCleanupVersionId: null,
        activeAnalysisRunId: null,
        version: 1,
        createdAt: "2026-08-01 00:00:00",
        updatedAt: "2026-08-01 01:00:00",
      }] : [],
    ));
    api.getCurrentCleanup.mockResolvedValue(null);
    api.getCleanup.mockResolvedValue(null);
    api.getAnalysisReport.mockResolvedValue(null);
    api.listCandidates.mockResolvedValue([]);
    api.listActions.mockResolvedValue([]);
    api.listRetrospectiveSearchReports.mockResolvedValue([]);
    api.listRetrospectiveSearches.mockResolvedValue([]);
  });

  it("keeps lifecycle tabs visible and applies a target deep link", async () => {
    renderPage("/retrospectives?jobTargetId=target-1");

    expect(await screen.findByRole("heading", { name: "面试复盘" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /进行中/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /已归档/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /回收站/ })).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "进行中 1" })).toBeVisible();
      expect(screen.getByRole("tab", { name: "已归档 0" })).toBeVisible();
      expect(screen.getByRole("tab", { name: "回收站 0" })).toBeVisible();
    });
    await screen.findByRole("option", { name: "星河科技 / 后端工程师" });
    expect(screen.getByLabelText("求职目标")).toHaveValue("target-1");
    expect(screen.getAllByText("星河科技后端一面")[0]).toBeVisible();
    expect(screen.getAllByText("2026/08/01")[0]).toBeVisible();
  });

  it("uses one full workspace empty state without leaving a duplicate detail pane", async () => {
    renderPage("/retrospectives?lifecycle=archived");

    expect(await screen.findByRole("heading", { name: "暂无已归档复盘" })).toBeVisible();
    expect(screen.queryByText("选择一场复盘")).not.toBeInTheDocument();
    expect(document.querySelector(".retrospective-page__workspace--empty")).toBeInTheDocument();
    expect(document.querySelector(".retrospective-page__controls")).toBeInTheDocument();
    expect(document.querySelector(".retrospective-page")?.children).toHaveLength(4);
    expect(screen.getByRole("button", { name: "历史检索" })).toBeInTheDocument();
  });

  it("opens workspace history search without loading a retrospective", async () => {
    renderPage("/retrospectives?mode=history");

    expect(await screen.findByRole("region", { name: "历史复盘检索" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "跨多场面试，找到问题和证据" })).toBeVisible();
    expect(screen.getByLabelText("搜索历史复盘")).toBeVisible();
    expect(screen.getByText("搜索不会重新读取你的简历、画像或完整转写，只使用已经确认的面试问题和当时已保存的正式分析。")).toBeVisible();
    expect(api.listRetrospectives).not.toHaveBeenCalled();
  });

  it("restores a history search from the URL search set id", async () => {
    api.getRetrospectiveSearch.mockResolvedValue({
      id: "search-2", workspaceId: "w1", queryText: "系统设计题", filters: {}, searchPlan: {},
      sessionId: "session-2", executionId: "execution-2", status: "completed",
      totalQuestions: 0, totalRetrospectives: 0, summaryMarkdown: "", summaryCitationQuestionIds: [],
      summaryExecutionId: null, lastErrorCode: null, version: 1, completedAt: "now", createdAt: "now", updatedAt: "now",
    });
    api.listRetrospectiveSearchResults.mockResolvedValue([]);

    renderPage("/retrospectives?mode=history&searchSetId=search-2");

    expect(await screen.findByRole("region", { name: "当前历史检索" })).toHaveTextContent("系统设计题");
    expect(api.getRetrospectiveSearch).toHaveBeenCalledWith("w1", "search-2", expect.anything());
  });

  it("enters a focused two-pane layout while reviewing the clean transcript", async () => {
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
      documentBody: "候选人：这是整理后的完整文字。",
      documentSha256: "sha256",
      completedItems: 1,
      totalItems: 1,
      activeItems: 0,
      failedItems: 0,
      currentWorkKey: null,
      lastErrorCode: null,
      version: 2,
      createdAt: "2026-08-01 00:00:00",
      updatedAt: "2026-08-01 00:00:04",
      segments: [],
      reviewIssues: [],
    });

    renderPage("/retrospectives?cleanupId=cleanup-1");

    expect(await screen.findByRole("button", { name: "复盘列表" })).toBeVisible();
    expect(await screen.findByLabelText("整理后的完整文字")).toBeVisible();
    expect(screen.queryByLabelText("面试复盘记录")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "星河科技后端一面" })).toHaveLength(1);
    expect(document.querySelector(".retrospective-page__workspace--focused")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "复盘列表" }));
    expect(await screen.findByLabelText("面试复盘记录")).toBeVisible();
  });

  it("does not request a null cleanup after the source is cleared", async () => {
    api.clearSourceVersion.mockResolvedValue({});
    renderPage("/retrospectives?jobTargetId=target-1");

    fireEvent.click(await screen.findByText("更多操作"));
    fireEvent.click(await screen.findByRole("button", { name: "清除原文" }));
    fireEvent.click(screen.getByRole("button", { name: "确认清除原文" }));

    await waitFor(() => expect(api.clearSourceVersion).toHaveBeenCalled());
    expect(api.getCleanup).not.toHaveBeenCalled();
  });

  it("keeps a saved retrospective when cleanup cannot start", async () => {
    const saved = {
      id: "retro-saved", workspaceId: "w1", jobTargetId: "target-1", title: "星河科技后端一面",
      roundLabel: "一面", interviewDate: "2026-08-01", outcome: "unrecorded", note: "",
      lifecycleStatus: "active", activeSourceVersionId: "source-saved", activeSourceAvailable: true, activeCleanupVersionId: null,
      activeAnalysisRunId: null, version: 2, createdAt: "now", updatedAt: "now",
    };
    api.listRetrospectives.mockResolvedValue([]);
    api.createRetrospective.mockResolvedValue(saved);
    api.addSourceVersion.mockResolvedValue({ id: "source-saved" });
    api.startCleanup.mockRejectedValue(new Error("请先配置面试复盘分析模型"));

    renderPage("/retrospectives?jobTargetId=target-1");
    fireEvent.click(await screen.findByRole("button", { name: "新建复盘" }));
    fireEvent.change(screen.getByLabelText("复盘名称"), { target: { value: "星河科技后端一面" } });
    fireEvent.change(screen.getByLabelText("面试轮次"), { target: { value: "一面" } });
    fireEvent.change(screen.getByLabelText("面试文字"), { target: { value: "面试官：介绍项目。\n候选人：这是我的回答。" } });
    fireEvent.click(screen.getByRole("button", { name: "开始整理" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("复盘和原文已保存");
    expect(screen.queryByRole("dialog", { name: "先保存文字，再交给 Agent 整理" })).toBeNull();
    expect(api.createRetrospective).toHaveBeenCalledTimes(1);
    expect(api.addSourceVersion).toHaveBeenCalledTimes(1);
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
    expect(await screen.findByText("还需处理 1 项")).toBeVisible();
    expect(api.getCleanup).toHaveBeenCalledWith("w1", "retro-1", "cleanup-1", expect.any(AbortSignal));
    fireEvent.change(screen.getByLabelText("第 1 段说话人"), { target: { value: "candidate" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));

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

    expect(await screen.findByText(/刷新或离开不会丢失已完成结果。/)).toBeVisible();
    expect(api.getCurrentCleanup).toHaveBeenCalledWith("w1", "retro-1", expect.any(AbortSignal));
    expect(api.getCleanup).toHaveBeenCalledWith("w1", "retro-1", "cleanup-current", expect.any(AbortSignal));
  });

  it("opens the failed question first and keeps completed results visible while analysis runs", async () => {
    api.listRetrospectives.mockResolvedValue([{
      id: "retro-1", workspaceId: "w1", jobTargetId: "target-1", title: "星河科技后端一面", roundLabel: "一面", interviewDate: "2026-08-01", outcome: "pending", note: "", lifecycleStatus: "active", activeSourceVersionId: "source-1", activeSourceAvailable: true, activeCleanupVersionId: "cleanup-1", activeAnalysisRunId: "run-1", version: 2, createdAt: "now", updatedAt: "now",
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
    expect(screen.getByRole("button", { name: "复盘列表" })).toBeVisible();
    expect(screen.queryByLabelText("面试复盘记录")).not.toBeInTheDocument();
    expect(screen.getByText("这道题分析失败")).toBeVisible();
    expect(screen.getByRole("button", { name: /已经完成的问题/ })).toBeVisible();
    expect(screen.queryByText(/总分/)).not.toBeInTheDocument();
  });

  it("retries only unfinished work in the existing failed analysis run", async () => {
    api.listRetrospectives.mockResolvedValue([{
      id: "retro-1", workspaceId: "w1", jobTargetId: "target-1", title: "星河科技后端一面", roundLabel: "一面", interviewDate: "2026-08-01", outcome: "pending", note: "", lifecycleStatus: "active", activeSourceVersionId: "source-1", activeSourceAvailable: true, activeCleanupVersionId: "cleanup-1", activeAnalysisRunId: "run-1", version: 2, createdAt: "now", updatedAt: "now",
    }]);
    api.getAnalysisReport.mockResolvedValue({
      analysisRun: { id: "run-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", executionId: "execution-1", retryOfAnalysisRunId: null, status: "failed", stage: "failed", controlIntent: null, completedItems: 2, totalItems: 4, currentWorkKey: null, cumulativeElapsedMs: 90_000, latestProgressAt: "now", summary: null, version: 2, createdAt: "now", updatedAt: "now" },
      questions: [{ id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "project", origin: "original", questionText: "分析失败的问题", questionSegmentIds: [], answerSegmentIds: [], inferenceBasis: "", confidence: .9, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" }],
      analyses: [],
      items: [{ id: "i-1", questionUnitId: "q-1", workKey: "question_analysis:q-1", status: "retryable", attemptCount: 2, lastErrorCode: "provider_timeout", updatedAt: "now" }],
      summary: {},
    });
    api.resumeAnalysis.mockResolvedValue({ analysisRunId: "run-1", executionId: "execution-2" });

    renderPage("/retrospectives?retrospectiveId=retro-1");
    fireEvent.click(await screen.findByRole("button", { name: "重试失败步骤" }));

    await waitFor(() => expect(api.resumeAnalysis).toHaveBeenCalledWith("w1", "retro-1", "run-1"));
    expect(api.retryAnalysis).not.toHaveBeenCalled();
  });
});
