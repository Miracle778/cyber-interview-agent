import { afterEach, describe, expect, it, vi } from "vitest";
import { submitReviewAnswer } from "./reviewApi";
import type { ReviewRound } from "./reviewTypes";

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
});
