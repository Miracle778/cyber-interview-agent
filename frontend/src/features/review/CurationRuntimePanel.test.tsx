import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurationRuntimePanel } from "./CurationRuntimePanel";
import type { CurationSession, QuestionCandidate } from "./reviewTypes";

const session = {
  id: "s1",
  stage: "waiting_for_command",
  summary: { items: [
    { ordinal: 1, candidateId: "c1", title: "MVCC", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" },
    { ordinal: 2, candidateId: "c2", title: "事务隔离", topics: ["database"], difficulty: "medium", sourceCount: 1, recommendation: "recommend_confirm" },
  ] },
  warnings: [],
  usage: { totalTokens: 20, callCount: 1 },
  contextUsage: { currentTokens: 32000, thresholdTokens: 89600 },
} as unknown as CurationSession;

function candidate(id: string, title: string, status: QuestionCandidate["status"], updatedAt = "2026-07-16T00:00:00Z"): QuestionCandidate {
  return {
    id,
    batchId: "b1",
    curationSessionId: "s1",
    sourceRefs: [],
    correctionNote: "",
    reviewNote: "",
    reviewNoteUpdatedAt: null,
    duplicateOfQuestionId: null,
    duplicateQuestion: null,
    status,
    draft: null,
    createdAt: "2026-07-16T00:00:00Z",
    updatedAt,
    question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: id, title, questionText: "问题", referenceAnswer: "答案", topics: ["database"], difficulty: "medium", keyPoints: [], followUps: [] },
  };
}

describe("CurationRuntimePanel candidate status", () => {
  afterEach(cleanup);
  it("replaces misleading task progress with live candidate cards", () => {
    const { rerender } = render(<CurationRuntimePanel session={session} candidates={[candidate("c1", "MVCC", "review_pending"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z")]} />);
    const status = screen.getByRole("region", { name: "候选题实时状态" });
    expect(status).toHaveTextContent("事务隔离");
    expect(within(status).getAllByRole("button")[0]).toHaveTextContent("待确认");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(screen.queryByText("当前任务")).toBeNull();
    expect(screen.queryByText("整体进度")).toBeNull();

    rerender(<CurationRuntimePanel session={{ ...session, summary: { items: [...session.summary.items, { ordinal: 3, candidateId: "c3", title: "间隙锁", topics: ["database"], difficulty: "hard", sourceCount: 1, recommendation: "recommend_confirm" }] } }} candidates={[candidate("c1", "MVCC", "published", "2026-07-16T00:02:00Z"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z"), candidate("c3", "间隙锁", "review_pending", "2026-07-16T00:03:00Z")]} />);

    expect(status).toHaveTextContent("间隙锁");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("2");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
  });

  it("drills into shared markdown cards and delegates the same file actions", () => {
    const onFilter = vi.fn();
    const onOpen = vi.fn();
    const onPublish = vi.fn();
    const onSaveNote = vi.fn();
    const candidates = [candidate("c1", "MVCC", "review_pending"), candidate("c3", "历史锁题", "review_pending")];
    const { rerender } = render(<CurationRuntimePanel session={session} candidates={candidates} onStatusFilterChange={onFilter} />);

    fireEvent.click(screen.getByRole("button", { name: /待确认/ }));
    expect(onFilter).toHaveBeenCalledWith("review_pending");

    rerender(<CurationRuntimePanel session={session} candidates={candidates} statusFilter="review_pending" onStatusFilterChange={onFilter} onOpenCandidate={onOpen} onPublishCandidate={onPublish} onSaveNote={onSaveNote} />);
    const files = screen.getByRole("list", { name: "待确认文件" });
    expect(within(files).getAllByRole("article")).toHaveLength(2);
    expect(within(files).getByText("历史版本")).toBeInTheDocument();
    fireEvent.click(within(files).getAllByRole("button", { name: "查看" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "发布" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "备注" })[0]);
    fireEvent.change(screen.getByLabelText("修改备注"), { target: { value: "补充例子" } });
    fireEvent.click(screen.getByRole("button", { name: "保存备注" }));

    expect(onOpen).toHaveBeenCalledWith("c1");
    expect(onPublish).toHaveBeenCalledWith("c1");
    expect(onSaveNote).toHaveBeenCalledWith("c1", "补充例子");
    expect(screen.queryByText("运行详情")).toBeNull();
  });
});
