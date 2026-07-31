import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EvaluationMetricMatrix } from "./EvaluationMetricMatrix";
import type { EvaluationRun } from "./evaluationTypes";


function run(id: string, score: number): EvaluationRun {
  return {
    id,
    workspaceId: "workspace-1",
    executionId: `execution-${id}`,
    evalPackId: "question-curation.v1",
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
      confidence: .82,
      summary: `${id} 的评分依据`,
      citedEventHashes: [`event-${id}-hash`],
      citedArtifactHashes: [`artifact-${id}-hash`],
      risks: ["边界样例不足"],
      evidenceGaps: [],
    }],
    deterministicResult: null,
    judgeSummary: null,
  };
}

afterEach(cleanup);

describe("EvaluationMetricMatrix", () => {
  it("shows baseline, candidate and delta as the primary comparison", () => {
    render(
      <EvaluationMetricMatrix
        baseline={run("baseline", 72)}
        candidate={run("candidate", 91)}
      />,
    );

    expect(screen.getByText("来源忠实度")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText("+19")).toBeInTheDocument();
  });

  it("reveals evidence and risks from the selected metric", () => {
    render(
      <EvaluationMetricMatrix
        baseline={run("baseline", 72)}
        candidate={run("candidate", 91)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /来源忠实度/ }));
    expect(screen.getByText("candidate 的评分依据")).toBeInTheDocument();
    expect(screen.getByText(/event-candidate/)).toBeInTheDocument();
    expect(screen.getByText(/artifact-candidate/)).toBeInTheDocument();
    expect(screen.getAllByText("82%")).toHaveLength(2);
    expect(screen.getAllByText("边界样例不足")).toHaveLength(2);
  });

  it("keeps a single-run report honest when no baseline is selected", () => {
    render(<EvaluationMetricMatrix baseline={null} candidate={run("candidate", 91)} />);

    expect(screen.getByText("尚未选择可对比的之前结果")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.queryByText("+19")).not.toBeInTheDocument();
  });
});
