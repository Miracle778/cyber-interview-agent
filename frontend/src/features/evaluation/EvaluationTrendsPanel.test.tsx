import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvaluationTrendsPanel } from "./EvaluationTrendsPanel";


const base = {
  bucket: "2026-07-30",
  graphId: "review.single",
  evalPackId: "review.v1",
  evalPackVersion: 1,
  judgeProviderModelId: "model-1",
  promptVersion: "p1",
  schemaVersion: "s1",
  toolVersion: "lookup@1",
  runCount: 4,
  successRate: .75,
  deterministicIssueRate: .25,
  averageJudgeScore: 82,
  humanReviewRate: .25,
  averageLatencyMs: 12000,
  averageTokens: 3200,
  averageContextTokens: 8000,
};

describe("EvaluationTrendsPanel", () => {
  it("keeps pack versions explicit and provides an accessible table", () => {
    render(<EvaluationTrendsPanel points={[
      base,
      { ...base, evalPackVersion: 2, promptVersion: "p2", averageJudgeScore: 91 },
    ]} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("82.0")).toBeInTheDocument();
    expect(within(table).getByText("91.0")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Eval Pack 版本"), {
      target: { value: "review.v1@2" },
    });
    expect(within(table).queryByText("82.0")).not.toBeInTheDocument();
    expect(within(table).getByText("91.0")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/cost|费用/i);
  });
});
