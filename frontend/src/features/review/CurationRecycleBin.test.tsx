import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurationRecycleBin } from "./CurationRecycleBin";

const deletedQuestion = {
  id: "candidate-trash-1",
  batchId: "batch-1",
  curationSessionId: "session-1",
  sourceRefs: [],
  correctionNote: "",
  reviewNote: "",
  reviewNoteUpdatedAt: null,
  duplicateOfQuestionId: null,
  duplicateQuestion: null,
  status: "review_pending",
  deletionReason: "不再需要",
  createdAt: "2026-08-06T01:00:00Z",
  updatedAt: "2026-08-06T01:00:00Z",
  question: {
    questionId: "question-1",
    documentId: "document-1",
    contentHash: "hash-1",
    title: "JVM 类加载过程",
    questionText: "JVM 类加载过程是什么？",
    referenceAnswer: "加载、链接、初始化",
    topics: ["Java"],
    difficulty: "medium",
    keyPoints: [],
    followUps: [],
  },
  draft: null,
};

function renderRecycleBin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CurationRecycleBin open workspaceId="workspace-1" onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

function mockRecycleBinFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/api/review/curation-sessions")) return Response.json([]);
    if (url.includes("/api/knowledge/sources")) return Response.json([]);
    if (url.includes("/api/review/question-candidates/recycle-bin/restore-all") && init?.method === "POST") {
      return Response.json({ affectedCount: 1 });
    }
    if (url.includes("/api/review/question-candidates/recycle-bin") && init?.method === "DELETE") {
      return Response.json({ affectedCount: 1 });
    }
    if (url.includes("/api/review/question-candidates/candidate-trash-1/permanent") && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    if (url.includes("/api/review/question-candidates")) return Response.json([deletedQuestion]);
    return Response.json({});
  });
}

describe("CurationRecycleBin", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("restores all deleted questions from the section toolbar", async () => {
    const fetchMock = mockRecycleBinFetch();
    renderRecycleBin();

    fireEvent.click(await screen.findByRole("button", { name: "全部恢复" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/question-candidates/recycle-bin/restore-all",
      expect.objectContaining({ method: "POST", body: '{"workspaceId":"workspace-1"}' }),
    ));
  });

  it("permanently deletes one question after confirmation", async () => {
    const fetchMock = mockRecycleBinFetch();
    vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    renderRecycleBin();

    fireEvent.click(await screen.findByRole("button", { name: "永久删除 JVM 类加载过程" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/question-candidates/candidate-trash-1/permanent",
      expect.objectContaining({ method: "DELETE" }),
    ));
  });

  it("empties deleted questions after destructive confirmation", async () => {
    const fetchMock = mockRecycleBinFetch();
    vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    renderRecycleBin();

    fireEvent.click(await screen.findByRole("button", { name: "清空题目" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/question-candidates/recycle-bin?workspaceId=workspace-1",
      expect.objectContaining({ method: "DELETE" }),
    ));
  });
});
