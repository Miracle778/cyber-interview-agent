import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvaluationCompareView } from "./EvaluationCompareView";
import type { EvaluationComparison, EvaluationRun } from "./evaluationTypes";


function run(id: string, score: number): EvaluationRun {
  return {
    id,
    workspaceId: "workspace-1",
    executionId: `execution-${id}`,
    evalPackId: "review.v1",
    evalPackVersion: 1,
    trigger: "regression",
    status: "completed",
    frozenInputHash: "a".repeat(64),
    judgeProviderModelId: "model-1",
    errorCode: null,
    createdAt: "2026-07-30T00:00:00Z",
    startedAt: null,
    completedAt: null,
    dimensions: [{
      dimensionId: "correctness",
      source: "judge",
      status: "scored",
      score,
      confidence: .8,
      summary: `评分 ${score}`,
      citedEventHashes: [],
      citedArtifactHashes: [],
      risks: [],
    }],
    deterministicResult: null,
    judgeSummary: null,
  };
}

describe("EvaluationCompareView", () => {
  it("aligns compatible dimensions in two explicit columns", () => {
    const comparison: EvaluationComparison = {
      evalPackId: "review.v1",
      evalPackVersion: 1,
      dimensionIds: ["correctness"],
      runs: [run("eval-one", 72), run("eval-two", 91)],
    };
    render(<EvaluationCompareView comparison={comparison} />);
    expect(screen.getByText("correctness")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getAllByText(/评分/)).toHaveLength(2);
  });
});
