import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
  it("replaces misleading task progress with live candidate cards", () => {
    const { rerender } = render(<CurationRuntimePanel session={session} candidates={[candidate("c1", "MVCC", "review_pending"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z")]} />);
    const status = screen.getByRole("region", { name: "候选题实时状态" });
    expect(status).toHaveTextContent("事务隔离");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
    expect(screen.queryByText("当前任务")).toBeNull();
    expect(screen.queryByText("整体进度")).toBeNull();

    rerender(<CurationRuntimePanel session={{ ...session, summary: { items: [...session.summary.items, { ordinal: 3, candidateId: "c3", title: "间隙锁", topics: ["database"], difficulty: "hard", sourceCount: 1, recommendation: "recommend_confirm" }] } }} candidates={[candidate("c1", "MVCC", "published", "2026-07-16T00:02:00Z"), candidate("c2", "事务隔离", "published", "2026-07-16T00:01:00Z"), candidate("c3", "间隙锁", "review_pending", "2026-07-16T00:03:00Z")]} />);

    expect(status).toHaveTextContent("间隙锁");
    expect(within(status).getByText("已发布", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("2");
    expect(within(status).getByText("待确认", { selector: ".curation-candidate-status__metrics span" }).previousSibling).toHaveTextContent("1");
  });
});
