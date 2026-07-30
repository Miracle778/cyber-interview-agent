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
  trigger: "manual",
  status: "completed",
  frozenInputHash: "hash",
  judgeProviderModelId: "judge-model",
  errorCode: null,
  createdAt: "2026-07-30T00:00:00Z",
  startedAt: null,
  completedAt: null,
  dimensions: [{
    dimensionId: "key_point_coverage",
    source: "judge",
    status: "scored",
    score: 88,
    confidence: .8,
    summary: "稳定",
    citedEventHashes: [],
    citedArtifactHashes: [],
    risks: [],
  }],
  deterministicResult: { status: "passed" },
  judgeSummary: null,
};

describe("EvaluationQualityRail", () => {
  it("separates policy from observed quality results", () => {
    render(<EvaluationQualityRail run={run} feedback={[]} />);

    expect(screen.getByRole("heading", { name: "质量门禁" })).toBeInTheDocument();
    expect(screen.getByText("确定性规则")).toBeInTheDocument();
    expect(screen.getByText("独立 Judge")).toBeInTheDocument();
    expect(screen.getByText("人工反馈")).toBeInTheDocument();
    expect(screen.getByText("1 项稳定")).toBeInTheDocument();
    expect(screen.getByText("复习评价质量")).toBeInTheDocument();
  });
});
