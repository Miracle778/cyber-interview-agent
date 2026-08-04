import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveCandidates } from "./RetrospectiveCandidates";
import type { InterviewQuestion, RetrospectiveCandidate } from "./retrospectiveTypes";

const questions: InterviewQuestion[] = [
  { id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "technical_knowledge", origin: "original", questionText: "缓存一致性怎么治理？", questionSegmentIds: [], answerSegmentIds: [], inferenceBasis: "", confidence: 1, decisionStatus: "confirmed", version: 1, createdAt: "now", updatedAt: "now" },
  { id: "q-2", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 2, questionKind: "project_experience", origin: "inferred", questionText: "项目里怎么落地？", questionSegmentIds: [], answerSegmentIds: [], inferenceBasis: "根据回答推断", confidence: .7, decisionStatus: "pending", version: 1, createdAt: "now", updatedAt: "now" },
];

const base = { retrospectiveId: "retro-1", analysisRunId: "run-1", fingerprint: "f", status: "pending" as const, targetResourceType: null, targetResourceId: null, lastErrorCode: null, version: 1, createdAt: "now", updatedAt: "now" };
const candidates: RetrospectiveCandidate[] = [
  { ...base, id: "c-review", questionUnitId: "q-1", candidateKind: "review_question", payload: { questionText: "缓存一致性怎么治理？" }, matches: [{ resourceId: "review-1", title: "如何治理缓存一致性？", score: .96 }] },
  { ...base, id: "c-project", questionUnitId: "q-1", candidateKind: "project_narrative", payload: { suggestedNarrative: "补充量化结果" }, matches: [] },
  { ...base, id: "c-summary", questionUnitId: null, candidateKind: "summary", payload: { title: "一面复盘" }, matches: [] },
];

afterEach(cleanup);

describe("RetrospectiveCandidates", () => {
  it("keeps all three groups visible and warns about pending inferred questions", () => {
    render(<MemoryRouter><RetrospectiveCandidates retrospectiveId="retro-1" candidates={candidates} questions={questions} busy={false} onDecision={vi.fn()} onBatchDecision={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("tab", { name: /复习题 1/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /项目与画像 1/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /复盘总结 1/ })).toBeVisible();
    expect(screen.getByText(/还有 1 道推断题待确认/)).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /项目与画像 1/ }));
    expect(screen.getByRole("tab", { name: /复习题 1/ })).toBeVisible();
    expect(screen.getByText("补充量化结果")).toBeVisible();
  });

  it("sends exact candidate IDs for a batch and exposes match decisions", () => {
    const onDecision = vi.fn();
    const onBatchDecision = vi.fn();
    render(<MemoryRouter><RetrospectiveCandidates retrospectiveId="retro-1" candidates={candidates} questions={questions} busy={false} onDecision={onDecision} onBatchDecision={onBatchDecision} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /关联已有题：如何治理缓存一致性/ }));
    expect(onDecision).toHaveBeenCalledWith(candidates[0], "link_existing", "review-1");
    fireEvent.click(screen.getByRole("checkbox", { name: /选择候选：缓存一致性怎么治理/ }));
    fireEvent.click(screen.getByRole("button", { name: /批量不加入资料库 1 项/ }));
    expect(onBatchDecision).toHaveBeenCalledWith([candidates[0]]);
  });

  it("lets an ignored candidate return to the pending list", () => {
    const onDecision = vi.fn();
    const rejected = [{ ...candidates[0], status: "rejected" as const, version: 2 }];
    render(<MemoryRouter><RetrospectiveCandidates retrospectiveId="retro-1" candidates={rejected} questions={questions} busy={false} onDecision={onDecision} onBatchDecision={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "恢复为待处理" }));
    expect(onDecision).toHaveBeenCalledWith(rejected[0], "reopen");
  });

  it("shows immediate practice only for an existing confirmed review question", () => {
    const confirmed = [{ ...candidates[0], status: "confirmed" as const, targetResourceType: "review_question", targetResourceId: "review-1" }];
    render(<MemoryRouter><RetrospectiveCandidates retrospectiveId="retro-1" candidates={confirmed} questions={questions} busy={false} onDecision={vi.fn()} onBatchDecision={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "立即练习" })).toHaveAttribute("href", "/review?questionId=review-1&source=retrospective&id=retro-1");
  });
});
