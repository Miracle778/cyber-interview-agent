import { describe, expect, it } from "vitest";
import type { QuestionCandidate } from "./reviewTypes";
import { groupLogicalQuestions } from "./questionGroups";

function candidate(id: string, status: QuestionCandidate["status"], text = "MySQL MVCC 如何工作？"): QuestionCandidate {
  return {
    id, batchId: `b-${id}`, curationSessionId: `s-${id}`, liveCurationSessionId: null,
    question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: `h-${id}`, title: "MVCC 原理", questionText: text, referenceAnswer: id, topics: ["并发控制"], difficulty: "medium", keyPoints: [], followUps: [] },
    sourceRefs: [], correctionNote: "", reviewNote: "", reviewNoteUpdatedAt: null,
    duplicateOfQuestionId: null, duplicateQuestion: null, status, draft: null,
    createdAt: `2026-07-1${id}T00:00:00Z`, updatedAt: `2026-07-1${id}T00:00:00Z`,
  };
}

describe("groupLogicalQuestions", () => {
  it("counts identical generated versions as one logical question and prefers the published version", () => {
    const pending = candidate("2", "review_pending", "请问 MySQL MVCC 如何工作？");
    const published = candidate("1", "published");
    const groups = groupLogicalQuestions([pending, published]);
    expect(groups).toHaveLength(1);
    expect(groups[0].primary.id).toBe("1");
    expect(groups[0].status).toBe("published");
    expect(groups[0].members).toHaveLength(2);
  });

  it("uses an explicit duplicate link even when wording differs", () => {
    const published = candidate("1", "published");
    const duplicate = { ...candidate("2", "review_pending", "MVCC 的 Read View 如何工作？"), duplicateOfQuestionId: "q-1" };
    expect(groupLogicalQuestions([published, duplicate])).toHaveLength(1);
  });

  it("prefers the sole active version when a logical question has publication history", () => {
    const historical = { ...candidate("1", "published"), isActiveVersion: false };
    const active = { ...candidate("2", "published"), question: { ...candidate("2", "published").question, questionId: "q-1" }, isActiveVersion: true };
    const groups = groupLogicalQuestions([historical, active]);
    expect(groups).toHaveLength(1);
    expect(groups[0].primary.id).toBe("2");
  });
});
