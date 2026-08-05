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
      evidenceRefs: [],
    }],
    deterministicResult: null,
    judgeSummary: null,
  };
}

function runWithDimensions(dimensions: EvaluationRun["dimensions"]): EvaluationRun {
  return { ...run("candidate", 91), dimensions };
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
    expect(screen.getAllByText("查看技术证据")).toHaveLength(2);
    expect(screen.getAllByText(/event-candidate/)[0]).not.toBeVisible();
    expect(screen.getAllByText(/artifact-candidate/)[0]).not.toBeVisible();
    expect(screen.getAllByText("边界样例不足")).toHaveLength(2);
  });

  it("uses a simpler result list when no baseline is selected", () => {
    render(<EvaluationMetricMatrix baseline={null} candidate={run("candidate", 91)} />);

    expect(screen.getByText("当前只显示本次检查结果；开启历史对比后可查看变化。")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "检查内容" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "本次结果" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "之前" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "变化" })).not.toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.queryByText("+19")).not.toBeInTheDocument();
  });

  it("keeps runtime safeguards in one collapsed Chinese group", () => {
    const candidate = runWithDimensions([
      run("candidate", 91).dimensions[0],
      {
        ...run("candidate", 91).dimensions[0],
        dimensionId: "runtime.late_result_protection",
        source: "deterministic",
        score: null,
        status: "inconclusive",
        applicability: "insufficient_evidence",
        summary: "Late result protection needs Receipt/Event proof.",
      },
    ]);

    render(<EvaluationMetricMatrix baseline={null} candidate={candidate} />);

    expect(screen.getByText("来源忠实度")).toBeInTheDocument();
    expect(screen.getByText("系统可靠性检查（1）")).toBeInTheDocument();
    expect(screen.getByText("任务结束后结果保护")).not.toBeVisible();
    expect(screen.queryByText(/Late result|Receipt|Event/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("系统可靠性检查（1）"));
    expect(screen.getByText("任务结束后结果保护")).toBeInTheDocument();
  });
});
