import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvaluationQualityRail } from "./EvaluationQualityRail";
import type { EvaluationRun } from "./evaluationTypes";


const run: EvaluationRun = {
  id: "eval-1",
  workspaceId: "workspace-1",
  executionId: "execution-1",
  evalPackId: "review.v1",
  evalPackVersion: 1,
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
  dimensions: [{
    dimensionId: "key_point_coverage",
    source: "judge",
    status: "scored",
    applicability: "applicable",
    rating: null,
    severity: null,
    score: 88,
    confidence: .8,
    summary: "稳定",
    citedEventHashes: [],
    citedArtifactHashes: [],
    risks: [],
    evidenceGaps: [],
  }],
  deterministicResult: { status: "passed" },
  judgeSummary: null,
};

describe("EvaluationQualityRail", () => {
  it("separates policy from observed quality results", () => {
    render(<EvaluationQualityRail run={run} feedback={[]} />);

    expect(screen.getByRole("heading", { name: "检查结论" })).toBeInTheDocument();
    expect(screen.getByText("基础规则检查")).toBeInTheDocument();
    expect(screen.getByText("AI 质量检查")).toBeInTheDocument();
    expect(screen.getByText("你的判断")).toBeInTheDocument();
    expect(screen.getByText("1 项稳定")).toBeInTheDocument();
    expect(screen.getByText("复习评价质量")).toBeInTheDocument();
    expect(screen.getByText("已配置")).toBeInTheDocument();
    expect(screen.queryByText("judge-model")).not.toBeInTheDocument();
  });
});
