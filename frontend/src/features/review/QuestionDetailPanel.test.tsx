import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionDetailPanel } from "./QuestionDetailPanel";
import type { QuestionCandidate } from "./reviewTypes";

const candidate: QuestionCandidate = {
  id: "c1", batchId: "b1", sourceRefs: ["s1"], correctionNote: "补齐异常场景", duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", createdAt: "now", updatedAt: "now",
  question: { questionId: "q1", documentId: "d1", contentHash: "h", title: "MVCC", questionText: "什么是 MVCC？", referenceAnswer: "多版本并发控制", topics: ["database"], difficulty: "medium", keyPoints: ["版本链"], followUps: [] },
  draft: { id: "d1", title: "MVCC", markdown: "# MVCC\n\n**多版本并发控制**", status: "review_pending", version: 1, contentHash: "h", documentType: "question" },
};

describe("QuestionDetailPanel", () => {
  afterEach(cleanup);
  it("renders Markdown by default and exposes source only on demand", () => {
    render(<QuestionDetailPanel candidate={candidate} sourceLabels={{ s1: "mysql.md" }} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByRole("article")).toHaveTextContent("多版本并发控制");
    expect(screen.queryByText("# MVCC", { exact: false })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Markdown 原文" }));
    expect(screen.getByText(/# MVCC/)).toBeInTheDocument();
    expect(screen.getByText("需要人工确认")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "来源证据" })).toHaveTextContent("mysql.md");
  });

  it("does not reserve a confirmation card for published questions", () => {
    render(<QuestionDetailPanel candidate={{ ...candidate, status: "published" }} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.queryByText("需要人工确认")).toBeNull();
  });

  it("shows the published question facts when a duplicate is detected", () => {
    render(<QuestionDetailPanel candidate={{ ...candidate, duplicateOfQuestionId: "q-old", duplicateQuestion: { ...candidate.question, questionId: "q-old", title: "已有 MVCC 题", questionText: "MVCC 的版本链是什么？" } }} sourceLabels={{}} busy={false} onSave={vi.fn()} onRewrite={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByText("已有 MVCC 题")).toBeInTheDocument();
    expect(screen.getByText("MVCC 的版本链是什么？")).toBeInTheDocument();
  });
});
