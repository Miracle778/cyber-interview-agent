import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createCurationSession,
  listCurationSessions,
  submitCurationCommand,
  submitReviewAnswer,
  interruptReviewEvaluation,
  retryReviewEvaluation,
  skipReviewQuestion,
  getBulkPublicationPreflight,
  pauseCurationSession,
  resumeCurationSession,
  startBulkPublication,
  terminateCurationSession,
  retryBulkPublication,
  retryCurationSeedTask,
  listAllQuestionCandidates,
} from "./reviewApi";
import type { CurationSession, ReviewRound } from "./reviewTypes";

describe("reviewApi", () => {
  afterEach(() => vi.restoreAllMocks());
  it("submits only the public input contract", async () => {
    const round = { id: "round-1", currentInput: { id: "input-1", version: 3 } } as ReviewRound;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(round));
    await submitReviewAnswer(round, "answer", "answer-key-123");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({ inputRequestId: "input-1", version: 3, idempotencyKey: "answer-key-123", value: "answer" });
    expect(body).not.toHaveProperty("sessionId");
    expect(body).not.toHaveProperty("executionId");
  });

  it("submits the selected model configuration for the current answer", async () => {
    const round = { id: "round-1", currentInput: { id: "input-1", version: 3 } } as ReviewRound;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(round));
    await submitReviewAnswer(round, "answer", "answer-key-123", "model-2", "high");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ providerModelId: "model-2", reasoningEffort: "high" });
  });

  it("retries the current failed evaluation with an idempotency key", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({}));
    await retryReviewEvaluation("round-1", "retry-evaluation-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/rounds/round-1/retry-evaluation",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ idempotencyKey: "retry-evaluation-1" }),
      }),
    );
  });

  it("interrupts evaluation and skips without requiring a pending input", async () => {
    const round = {
      id: "round-1",
      currentInput: null,
      attempts: [{ status: "evaluating" }],
    } as ReviewRound;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => Response.json(round),
    );

    await interruptReviewEvaluation("round-1", "interrupt-evaluation-1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/rounds/round-1/interrupt-evaluation",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          idempotencyKey: "interrupt-evaluation-1",
        }),
      }),
    );

    await skipReviewQuestion(round, "skip-evaluation-1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/rounds/round-1/skip",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ idempotencyKey: "skip-evaluation-1" }),
      }),
    );
  });

  it("uses the durable curation session contract", async () => {
    const session = { id: "curation-1", summaryVersion: 4 } as CurationSession;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json(session));

    await listCurationSessions("w1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/curation-sessions?workspaceId=w1",
      expect.objectContaining({ method: "GET" }),
    );

    await createCurationSession("w1", ["source-1", "source-2"]);
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      workspaceId: "w1",
      sourceRefs: ["source-1", "source-2"],
    });

    await submitCurationCommand(
      session,
      "确认全部推荐题",
      "curation-command-1",
      "provider-model-1",
      "high",
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/curation-sessions/curation-1/commands",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      text: "确认全部推荐题",
      summaryVersion: 4,
      idempotencyKey: "curation-command-1",
      providerModelId: "provider-model-1",
      reasoningEffort: "high",
    });

    await getBulkPublicationPreflight("curation-1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/curation-sessions/curation-1/bulk-publication/preflight",
      expect.objectContaining({ method: "GET" }),
    );
    await startBulkPublication(
      "curation-1",
      4,
      ["candidate-1"],
      "bulk-start-1",
    );
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      summaryVersion: 4,
      candidateIds: ["candidate-1"],
      idempotencyKey: "bulk-start-1",
      confirmedAiCandidateIds: [],
    });
    await retryBulkPublication("bulk-1", "bulk-retry-1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/bulk-publications/bulk-1/retry",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ idempotencyKey: "bulk-retry-1" }),
      }),
    );
  });

  it("loads the candidate catalog in large pages instead of issuing one request per 50 items", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json([]));

    await listAllQuestionCandidates("w1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/review/question-candidates?workspaceId=w1&page=1&pageSize=500",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it.each([
    ["pause", pauseCurationSession],
    ["resume", resumeCurationSession],
    ["terminate", terminateCurationSession],
  ] as const)("sends %s idempotency in the header and only the expected Batch version in the body", async (operation, request) => {
    const session = { id: "curation-1", batchVersion: 8 } as CurationSession;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(session, { status: 202 }));

    await request("curation-1", 7, `${operation}-request-0001`);

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/review/curation-sessions/curation-1/${operation}`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "Idempotency-Key": `${operation}-request-0001`,
        }),
        body: JSON.stringify({ expectedBatchVersion: 7 }),
      }),
    );
  });

  it("retries exactly one seed with versioned body and header idempotency", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ receiptId: "receipt-1", seedTaskId: "seed-1", executionId: "execution-1", status: "accepted" }, { status: 202 }));
    await retryCurationSeedTask("curation-1", "seed-1", 3, "retry-seed-0001");
    expect(fetchMock).toHaveBeenCalledWith("/api/review/curation-sessions/curation-1/seed-tasks/seed-1/retry", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "retry-seed-0001" }),
      body: JSON.stringify({ expectedVersion: 3 }),
    }));
  });
});
