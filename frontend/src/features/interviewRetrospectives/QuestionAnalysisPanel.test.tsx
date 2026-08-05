import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionAnalysisPanel } from "./QuestionAnalysisPanel";
import type { InterviewQuestion, QuestionAnalysis } from "./retrospectiveTypes";

const question: InterviewQuestion = { id: "q-1", retrospectiveId: "retro-1", cleanupVersionId: "cleanup-1", ordinal: 1, questionKind: "project", origin: "inferred", questionText: "如何处理缓存击穿？", questionSegmentIds: [], answerSegmentIds: ["s-2"], inferenceBasis: "recordingCoverage=candidate_only；回答提到了热 Key", confidence: .72, decisionStatus: "pending", version: 1, createdAt: "now", updatedAt: "now" };
const analysis: QuestionAnalysis = { id: "a-1", analysisRunId: "run-1", questionUnitId: "q-1", verdict: "improvable", strengths: [{ summary: "指出了互斥锁", evidenceSegmentIds: ["s-2"] }], improvements: [{ summary: "补充锁超时策略", evidenceSegmentIds: [] }], omissions: [], gaps: [{ kind: "depth", summary: "缺少异常分支", evidenceSegmentIds: [] }], evidenceLevel: "model_judgment", confidence: .8, improvementOutline: ["先说明风险", "再说明保护策略"], suggestedAnswer: "可以使用互斥锁，并设置超时与降级。", sourceExcerpt: "", sourceAvailable: false, resultStatus: "draft", version: 1 };

afterEach(cleanup);

describe("QuestionAnalysisPanel", () => {
  it("asks for an inferred-question decision and explains cleared evidence", () => {
    const onDecision = vi.fn();
    render(<MemoryRouter><QuestionAnalysisPanel question={question} analysis={analysis} item={null} executionId="execution-1" returnTo="/retrospectives?retrospectiveId=retro-1&questionId=q-1" busy={false} onDecision={onDecision} /></MemoryRouter>);
    expect(screen.getByText("这是一道推断题，请先确认")).toBeVisible();
    expect(screen.getByText("这份录音主要保留了候选人的回答；回答提到了热 Key")).toBeVisible();
    expect(screen.queryByText(/recordingCoverage/)).not.toBeInTheDocument();
    expect(screen.getByText("模型判断，建议核对")).toBeVisible();
    expect(screen.getByText("原始文字已清除，当前仅保留分析结论")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认是面试题" }));
    expect(onDecision).toHaveBeenCalledWith("confirmed");
    expect(screen.getByRole("link", { name: "查看高级运行详情" })).toHaveAttribute("href", expect.stringContaining("/agents/executions/execution-1"));
  });

  it("keeps long evidence and reference copy behind progressive disclosure", () => {
    const sourceAnalysis = { ...analysis, sourceAvailable: true, sourceExcerpt: "这是很长的回答原文。", suggestedAnswer: "这是整理后的参考表达。" };
    const { container } = render(<MemoryRouter><QuestionAnalysisPanel question={{ ...question, decisionStatus: "confirmed" }} analysis={sourceAnalysis} item={null} executionId={null} returnTo="/retrospectives" busy={false} onDecision={vi.fn()} /></MemoryRouter>);

    expect(screen.getByText("本题结论")).toBeVisible();
    expect(screen.getByText("推荐回答结构")).toBeVisible();
    expect(screen.getByText("查看回答原文")).toBeVisible();
    expect(screen.getByText("查看参考表达")).toBeVisible();
    expect(container.querySelector("details[open]")).not.toBeInTheDocument();
  });
});
