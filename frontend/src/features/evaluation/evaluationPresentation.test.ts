import { describe, expect, it } from "vitest";
import type { EvaluationDimension, EvaluationRun } from "./evaluationTypes";
import {
  dimensionLabel,
  dimensionOutcome,
  evaluationPackLabel,
  evaluationStatusMeta,
  formatEvaluationVersion,
  summarizeEvaluation,
} from "./evaluationPresentation";


function dimension(
  score: number | null,
  status = score === null ? "passed" : "scored",
): EvaluationDimension {
  return {
    dimensionId: "source_fidelity",
    source: score === null ? "deterministic" : "judge",
    status,
    applicability: "applicable",
    rating: null,
    severity: null,
    score,
    confidence: score === null ? null : .8,
    summary: "测试结论",
    citedEventHashes: [],
    citedArtifactHashes: [],
    risks: [],
    evidenceGaps: [],
    evidenceRefs: [],
  };
}

function run(dimensions: EvaluationDimension[]): EvaluationRun {
  return {
    id: "eval-1",
    workspaceId: "workspace-1",
    executionId: "execution-1",
    evalPackId: "question-curation.v1",
    evalPackVersion: 2,
    evaluationContractVersion: 1,
    taskType: "legacy",
    runKind: "historical_review",
    trigger: "manual",
    status: "completed",
    frozenInputHash: "hash",
    businessOutcomeHash: null,
    judgeDataScope: {},
    judgeProviderModelId: "judge-model",
    errorCode: null,
    createdAt: "2026-07-30T00:00:00Z",
    startedAt: null,
    completedAt: null,
    dimensions,
    deterministicResult: null,
    judgeSummary: null,
  };
}

describe("evaluation presentation semantics", () => {
  it("translates packs, dimensions and statuses into business language", () => {
    expect(evaluationPackLabel("question-curation.v1")).toBe("题目整理质量");
    expect(dimensionLabel("source_fidelity")).toBe("来源忠实度");
    expect(evaluationStatusMeta("completed").label).toBe("评估完成");
    expect(formatEvaluationVersion(run([]))).toBe("题目整理质量 · v2");
  });

  it("uses readable fallbacks for unknown identifiers", () => {
    expect(evaluationPackLabel("new-agent_pack.v3")).toBe("New Agent Pack");
    expect(dimensionLabel("novel_quality_signal")).toBe("Novel Quality Signal");
  });

  it("derives display tones without pretending they are backend gates", () => {
    expect(dimensionOutcome(dimension(92)).tone).toBe("success");
    expect(dimensionOutcome(dimension(72)).tone).toBe("neutral");
    expect(dimensionOutcome(dimension(61)).tone).toBe("warning");
    expect(dimensionOutcome(dimension(40)).tone).toBe("danger");
    expect(dimensionOutcome(dimension(null, "failed")).tone).toBe("danger");
    expect(dimensionOutcome(dimension(null, "inconclusive"))).toEqual({
      label: "证据不足",
      tone: "warning",
    });
  });

  it("summarizes only observed results and the latest human verdict", () => {
    const summary = summarizeEvaluation(
      run([
        dimension(90),
        { ...dimension(60), dimensionId: "coverage" },
        { ...dimension(null, "failed"), dimensionId: "trace_complete" },
      ]),
      [{
        id: "feedback-1",
        workspaceId: "workspace-1",
        evalRunId: "eval-1",
        version: 1,
        verdict: "uncertain",
        dimensionId: null,
        reason: null,
        createdAt: "2026-07-30T00:01:00Z",
      }],
    );

    expect(summary).toEqual({
      passed: 1,
      attention: 1,
      failed: 1,
      averageScore: 75,
      humanVerdict: "uncertain",
    });
  });
});
