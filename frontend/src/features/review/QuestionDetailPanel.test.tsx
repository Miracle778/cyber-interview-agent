import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionDetailPanel } from "./QuestionDetailPanel";
import type { QuestionCandidate } from "./reviewTypes";

const candidate: QuestionCandidate = {
  id: "c1", batchId: "b1", curationSessionId: "session-1", sourceRefs: ["s1"], correctionNote: "补齐异常场景", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", createdAt: "now", updatedAt: "now",
  question: { questionId: "q1", documentId: "d1", contentHash: "h", title: "MVCC", questionText: "什么是 MVCC？", referenceAnswer: "多版本并发控制", topics: ["database"], difficulty: "medium", keyPoints: ["版本链"], followUps: [] },
  draft: { id: "d1", title: "MVCC", markdown: "# MVCC\n\n**多版本并发控制**", status: "review_pending", version: 1, contentHash: "h", documentType: "question" },
};

describe("QuestionDetailPanel", () => {
  afterEach(cleanup);
  it("renders Markdown for reading and edits the source in the second mode", () => {
    const onSave = vi.fn();
    render(<QuestionDetailPanel candidate={candidate} sourceLabels={{ s1: "mysql.md" }} busy={false} onSave={onSave} onRewrite={vi.fn()} onConfirm={vi.fn()} onOpenSession={vi.fn()} />);
    expect(screen.getByRole("article")).toHaveTextContent("多版本并发控制");
    expect(screen.queryByText("# MVCC", { exact: false })).toBeNull();
    expect(screen.getByRole("button", { name: "阅读" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "编辑" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "原文" }));
    const source = screen.getByRole("textbox", { name: "Markdown 原文" });
    expect((source as HTMLTextAreaElement).value).toContain("# MVCC");
    fireEvent.change(source, { target: { value: "# MVCC 新标题\n\n## 题目\n\n新的问题\n\n## 参考答案\n\n新的答案\n\n## 关键点\n\n- 快照\n- 版本链" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onSave).toHaveBeenCalledWith({ version: 1, title: "MVCC 新标题", questionText: "新的问题", referenceAnswer: "新的答案", keyPoints: ["快照", "版本链"] });
    expect(screen.getByText("确认后进入发布审批")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "来源证据" })).toHaveTextContent("mysql.md");
  });

  it("does not reserve a confirmation card for published questions", () => {
    render(<QuestionDetailPanel candidate={{ ...candidate, status: "published" }} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} onOpenSession={vi.fn()} />);
    expect(screen.queryByText("需要人工确认")).toBeNull();
  });

  it("shows the published question facts when a duplicate is detected", () => {
    render(<QuestionDetailPanel candidate={{ ...candidate, duplicateOfQuestionId: "q-old", duplicateQuestion: { ...candidate.question, questionId: "q-old", title: "已有 MVCC 题", questionText: "MVCC 的版本链是什么？" } }} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} onOpenSession={vi.fn()} />);
    expect(screen.getByText("已有 MVCC 题")).toBeInTheDocument();
    expect(screen.getByText("MVCC 的版本链是什么？")).toBeInTheDocument();
  });

  it("opens the generating curation session for contextual rewriting", () => {
    const onOpenSession = vi.fn();
    render(<QuestionDetailPanel candidate={candidate} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} onOpenSession={onOpenSession} />);

    fireEvent.click(screen.getByRole("button", { name: "查看生成会话" }));

    expect(onOpenSession).toHaveBeenCalledWith("c1");
  });

  it("keeps AI provenance and material support visible before publication", () => {
    render(<QuestionDetailPanel candidate={{ ...candidate, answerBasis: "model", materialSupport: "minimal", needsReview: true, normalizationIssues: ["repaired_title"] }} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} onOpenSession={vi.fn()} />);
    expect(screen.getByRole("note")).toHaveTextContent("主要由 AI 生成");
    expect(screen.getByRole("note")).toHaveTextContent("原资料提供的支撑很少");
    expect(screen.getByText(/下一步会要求明确确认/)).toBeInTheDocument();
  });

  it("shows the rejection reason and carries it into the next revision", () => {
    const onRewrite = vi.fn();
    const onSave = vi.fn();
    render(<QuestionDetailPanel candidate={{ ...candidate, status: "rejected", rejectionReason: "补充故障恢复步骤", rejectedAt: "2026-07-18T08:00:00Z", rejectionActionId: "action-1", draft: { ...candidate.draft!, status: "rejected" } }} sourceLabels={{}} busy={false} onSave={onSave} onRewrite={onRewrite} onConfirm={vi.fn()} onOpenSession={vi.fn()} />);

    expect(screen.getByText("退回修改原因")).toBeInTheDocument();
    expect(screen.getByText("补充故障恢复步骤")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "按退回原因让 AI 在原会话中重写" })).toHaveValue("补充故障恢复步骤");
    fireEvent.click(screen.getByRole("button", { name: "重新整理" }));
    expect(onRewrite).toHaveBeenCalledWith("补充故障恢复步骤");

    fireEvent.click(screen.getByRole("button", { name: "手动修改" }));
    expect(screen.getByRole("textbox", { name: "Markdown 原文" })).toBeInTheDocument();
  });
});
