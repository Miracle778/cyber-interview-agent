import { describe, expect, it } from "vitest";
import { toActionableError } from "./errorAdvice";

describe("runtime guard advice", () => {
  it.each([
    "loop_detected",
    "no_progress",
    "step_budget_exceeded",
    "token_budget_exceeded",
    "run_timeout",
  ])("returns actionable advice for %s", (code) => {
    const result = toActionableError(new Error(code), "failed");
    expect(result.advice).toContain("下一步");
    expect(result.advice).not.toContain("检查当前步骤输入");
  });
});
