import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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
    evidenceRefs: [],
  }],
  deterministicResult: { status: "passed" },
  judgeSummary: null,
};

afterEach(cleanup);

describe("EvaluationQualityRail", () => {
  it("leads with the user outcome and keeps methodology secondary", () => {
    render(<EvaluationQualityRail run={run} feedback={[]} />);

    expect(screen.getByRole("heading", { name: "可以使用" })).toBeInTheDocument();
    expect(screen.getByText("本次结论")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "优先处理" })).toBeInTheDocument();
    expect(screen.getByText("查看检查方式")).toBeInTheDocument();
    expect(screen.getByText("证据完整性检查")).toBeInTheDocument();
    expect(screen.getByText("AI 质量检查")).toBeInTheDocument();
    expect(screen.getByText("你的判断")).toBeInTheDocument();
    expect(screen.getByText("1 项稳定")).toBeInTheDocument();
    expect(screen.getByText("查看检查设置")).toBeInTheDocument();
    expect(screen.getByText("复习评价质量")).toBeInTheDocument();
    expect(screen.getByText("已配置")).toBeInTheDocument();
    expect(screen.queryByText("judge-model")).not.toBeInTheDocument();
  });

  it("shows evidence gaps among the three highest-priority issues", () => {
    render(<EvaluationQualityRail run={{
      ...run,
      dimensions: [{
        ...run.dimensions[0],
        dimensionId: "history_source_coverage",
        applicability: "insufficient_evidence",
        score: null,
        summary: "缺少部分历史场次来源",
      }],
    }} feedback={[]} />);

    expect(screen.getByRole("heading", { name: "建议核对" })).toBeInTheDocument();
    expect(screen.getByText("缺少部分历史场次来源")).toBeInTheDocument();
    expect(screen.queryByText("没有需要优先处理的问题。")).not.toBeInTheDocument();
  });

  it("turns runtime rule warnings into plain Chinese guidance", () => {
    render(<EvaluationQualityRail run={{
      ...run,
      dimensions: [{
        ...run.dimensions[0],
        dimensionId: "runtime.source_version_integrity",
        source: "deterministic",
        applicability: "insufficient_evidence",
        score: null,
        summary: "Receipt/Event/hash/locator validation is incomplete.",
      }],
    }} feedback={[]} />);

    expect(screen.getByText("已有来源记录，但还不能完整确认对应版本和原文位置。")).toBeInTheDocument();
    expect(screen.queryByText(/Receipt|Event|hash|locator/)).not.toBeInTheDocument();
  });
});
