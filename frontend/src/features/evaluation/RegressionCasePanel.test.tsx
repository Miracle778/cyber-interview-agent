import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RegressionCasePanel } from "./RegressionCasePanel";
import type { RegressionCase, RegressionRun } from "./evaluationTypes";

const regressionCase: RegressionCase = {
  id: "case-1",
  executionId: "execution-1234567890",
  evalPackId: "review-discussion.v2",
  evalPackVersion: 2,
  evaluationContractVersion: 2,
  runKind: "historical_review",
  version: 1,
  snapshotHash: "a".repeat(64),
  containsPrivateBodies: true,
  redactionSummary: "保留经确认的任务正文",
  caseContractVersion: 2,
  taskType: "review_discussion",
  privacyManifest: {},
  baselineVersions: {},
  runnable: true,
  unavailableReason: null,
  availableImplementationIds: ["source-model-config@current-code", "current-runtime"],
  createdAt: "2026-07-31T18:00:00Z",
};

const regressionRun: RegressionRun = {
  id: "regression-1",
  caseId: "case-1",
  caseVersion: 1,
  status: "completed",
  baselineImplementationId: "source-model-config@current-code",
  candidateImplementationId: "current-runtime",
  baselineExecutionId: "baseline-1",
  candidateExecutionId: "candidate-1",
  baselineOutcomeHash: "b".repeat(64),
  candidateOutcomeHash: "c".repeat(64),
  deterministicComparison: {},
  pairwiseResult: { winner: "tie" },
  infrastructureFailures: [],
  isolationManifest: {
    separateSandboxes: true,
    productionWrites: false,
    baselineVersions: { graph: "review.discussion@1", codeMode: "current_process" },
    candidateVersions: { graph: "review.discussion@1", codeMode: "current_process" },
  },
  errorCode: null,
  createdAt: "2026-07-31T18:00:00Z",
  startedAt: "2026-07-31T18:00:00Z",
  completedAt: "2026-07-31T18:00:15Z",
};

describe("RegressionCasePanel", () => {
  it("explains the latest real regression instead of exposing a raw status", () => {
    render(
      <RegressionCasePanel
        run={null}
        cases={[regressionCase]}
        pending={false}
        onCreate={vi.fn()}
        regressionRuns={[regressionRun]}
        onRun={vi.fn()}
      />,
    );

    expect(screen.getByText("回归已完成")).toBeInTheDocument();
    expect(screen.getByText("盲评结论：整体持平")).toBeInTheDocument();
    expect(screen.queryByText("最近回归：completed")).not.toBeInTheDocument();

    const details = screen.getByText("查看本次回归依据").closest("details");
    expect(details).not.toBeNull();
    details!.open = true;
    expect(screen.getByText("双沙箱 · 未写正式工作区")).toBeInTheDocument();
    expect(screen.getByText("无异常")).toBeInTheDocument();
  });

  it("maps remapped blind-review winners back to product terminology", () => {
    render(
      <RegressionCasePanel
        run={null}
        cases={[regressionCase]}
        pending={false}
        onCreate={vi.fn()}
        regressionRuns={[{
          ...regressionRun,
          pairwiseResult: { winner: "candidate" },
        }]}
        onRun={vi.fn()}
      />,
    );

    expect(screen.getByText("盲评结论：当前配置略优")).toBeInTheDocument();
  });
});
