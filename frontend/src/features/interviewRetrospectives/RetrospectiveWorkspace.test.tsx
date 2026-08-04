import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveWorkspace } from "./RetrospectiveWorkspace";
import type { AnalysisReport, InterviewRetrospective } from "./retrospectiveTypes";

const retrospective: InterviewRetrospective = { id: "retro-1", workspaceId: "w1", jobTargetId: "target-1", title: "后端一面复盘", roundLabel: "一面", interviewDate: "2026-08-01", outcome: "pending", note: "", lifecycleStatus: "active", activeSourceVersionId: "source-1", activeSourceAvailable: true, activeCleanupVersionId: "cleanup-1", activeAnalysisRunId: "run-1", version: 2, createdAt: "now", updatedAt: "now" };
const report: AnalysisReport = {
  analysisRun: { id: "run-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", executionId: "execution-1", retryOfAnalysisRunId: null, status: "running", stage: "question_analysis", controlIntent: null, completedItems: 1, totalItems: 3, currentWorkKey: "question_analysis:q-2", cumulativeElapsedMs: 2_000, latestProgressAt: "now", summary: null, version: 2, createdAt: "now", updatedAt: "now" },
  questions: [{ id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "project", origin: "original", questionText: "介绍一下缓存治理", questionSegmentIds: ["s-1"], answerSegmentIds: ["s-2"], inferenceBasis: "", confidence: .99, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" }],
  analyses: [{ id: "a-1", analysisRunId: "run-1", questionUnitId: "q-1", verdict: "strong", strengths: [{ summary: "结构清晰", evidenceSegmentIds: ["s-2"] }], improvements: [], omissions: [], gaps: [], evidenceLevel: "direct", confidence: .92, improvementOutline: [], suggestedAnswer: "", sourceExcerpt: "回答原文", sourceAvailable: true, resultStatus: "completed", version: 1 }],
  items: [{ id: "i-1", questionUnitId: "q-1", workKey: "question_analysis:q-1", status: "completed", attemptCount: 1, lastErrorCode: null, updatedAt: "now" }],
  summary: { highRiskCount: 0 },
};

const workspaceProps = {
  candidates: [],
  actions: [],
  publicationDraft: null,
  candidateBusy: false,
  actionBusy: false,
  publicationBusy: false,
  onCandidateDecision: vi.fn(),
  onBatchCandidateDecision: vi.fn(),
  onActionDecision: vi.fn(),
  onCreateDraft: vi.fn(),
};

afterEach(cleanup);

describe("RetrospectiveWorkspace", () => {
  it("renders completed questions before finalization without an overall score", () => {
    render(<MemoryRouter><RetrospectiveWorkspace {...workspaceProps} retrospective={retrospective} report={report} selectedQuestionId="q-1" busy={false} onSelectQuestion={vi.fn()} onStop={vi.fn()} onResume={vi.fn()} onRetry={vi.fn()} onDecision={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "介绍一下缓存治理" })).toBeVisible();
    expect(screen.getAllByText("结构清晰")[0]).toBeVisible();
    expect(screen.queryByText(/总分/)).not.toBeInTheDocument();
    expect(screen.getByText("分析仍在继续，已完成的问题可以先看")).toBeVisible();
  });

  it("keeps review, assets, and action views visible while switching", () => {
    render(<MemoryRouter><RetrospectiveWorkspace {...workspaceProps} retrospective={retrospective} report={report} selectedQuestionId="q-1" busy={false} onSelectQuestion={vi.fn()} onStop={vi.fn()} onResume={vi.fn()} onRetry={vi.fn()} onDecision={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("tab", { name: /逐题复盘 1/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /保存成果 0/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /下一步 0/ })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /保存成果 0/ }));
    expect(screen.getByRole("heading", { name: "选择要保存的内容" })).toBeVisible();
    expect(screen.getByRole("tab", { name: /逐题复盘 1/ })).toBeVisible();
  });

  it("keeps confirmed transcript revisions available from the analysis workspace", () => {
    render(<MemoryRouter><RetrospectiveWorkspace
      {...workspaceProps}
      retrospective={retrospective}
      report={report}
      corrections={[{
        id: "correction-1",
        segmentId: "s-2",
        sourceStart: 10,
        sourceEnd: 14,
        originalText: "卡夫卡",
        suggestedText: "Kafka",
        adoptedText: "Kafka",
        changeType: "recognition",
        riskLevel: "low",
        reason: "技术名词识别修正",
        confidence: 0.96,
        decision: "auto_accepted",
      }]}
      selectedQuestionId="q-1"
      busy={false}
      onSelectQuestion={vi.fn()}
      onStop={vi.fn()}
      onResume={vi.fn()}
      onRetry={vi.fn()}
      onDecision={vi.fn()}
    /></MemoryRouter>);

    fireEvent.click(screen.getByText("已修订 1 处 · 查看原文对照"));
    expect(screen.getByText("卡夫卡")).toBeVisible();
    expect(screen.getByText("Kafka")).toBeVisible();
    expect(screen.getByText("技术名词识别修正")).toBeVisible();
  });
});
