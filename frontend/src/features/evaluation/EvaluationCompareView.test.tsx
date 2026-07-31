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
    evaluationContractVersion: 1,
    taskType: "legacy",
    runKind: "historical_review",
    trigger: "regression",
    status: "completed",
    frozenInputHash: "a".repeat(64),
    businessOutcomeHash: null,
    judgeDataScope: {},
    judgeProviderModelId: "model-1",
    errorCode: null,
    createdAt: "2026-07-30T00:00:00Z",
    startedAt: null,
    completedAt: null,
    dimensions: [{
      dimensionId: "source_fidelity",
      source: "judge",
      status: "scored",
      applicability: "applicable",
      rating: null,
      severity: null,
      score,
      confidence: .8,
      summary: `评分 ${score}`,
      citedEventHashes: [],
      citedArtifactHashes: [],
      risks: [],
      evidenceGaps: [],
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
      dimensionIds: ["source_fidelity"],
      runs: [run("eval-one", 72), run("eval-two", 91)],
    };
    render(<EvaluationCompareView comparison={comparison} />);
    expect(screen.getByText("来源忠实度")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText("+19")).toBeInTheDocument();
  });
});
