import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createCurationSession,
  listCurationSessions,
  submitCurationCommand,
  submitReviewAnswer,
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

    await submitCurationCommand(session, "确认全部推荐题", "curation-command-1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/review/curation-sessions/curation-1/commands",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      text: "确认全部推荐题",
      summaryVersion: 4,
      idempotencyKey: "curation-command-1",
    });
  });
});
