import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveLifecycleActions } from "./RetrospectiveLifecycleActions";
import type { InterviewRetrospective } from "./retrospectiveTypes";

const api = vi.hoisted(() => ({
  clearSourceVersion: vi.fn(),
  getRetrospectiveDeletionImpact: vi.fn(),
  permanentlyDeleteRetrospective: vi.fn(),
  transitionRetrospective: vi.fn(),
}));

vi.mock("./retrospectiveApi", () => api);

function retrospective(lifecycleStatus: InterviewRetrospective["lifecycleStatus"]): InterviewRetrospective {
  return {
    id: "retro-1", workspaceId: "w1", jobTargetId: "target-1", title: "后端一面",
    roundLabel: "一面", interviewDate: "2026-08-01", outcome: "failed", note: "",
    lifecycleStatus, activeSourceVersionId: "source-1", activeSourceAvailable: true, activeCleanupVersionId: "cleanup-1",
    activeAnalysisRunId: "run-1", version: 3, createdAt: "", updatedAt: "",
  };
}

describe("retrospective lifecycle actions", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    api.transitionRetrospective.mockResolvedValue(retrospective("archived"));
    api.clearSourceVersion.mockResolvedValue({});
    api.permanentlyDeleteRetrospective.mockResolvedValue(undefined);
    api.getRetrospectiveDeletionImpact.mockResolvedValue({
      sourceVersions: 1, cleanupVersions: 2, analysisRuns: 3, candidates: 4, actionItems: 5,
      preservesReviewQuestions: true, preservesProfileAndProjects: true, preservesKnowledge: true,
    });
  });

  it("explains lost capabilities before clearing the source", async () => {
    const onChanged = vi.fn();
    render(<RetrospectiveLifecycleActions retrospective={retrospective("active")} onChanged={onChanged} onError={vi.fn()} />);

    fireEvent.click(screen.getByText("更多操作"));
    fireEvent.click(screen.getByRole("button", { name: "清除原文" }));
    expect(screen.getByText(/无法再查看转写、核对原文引用/)).toBeVisible();
    expect(screen.getByText(/已确认的问题、结论、准备资产和行动项会保留/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认清除原文" }));

    await waitFor(() => expect(api.clearSourceVersion).toHaveBeenCalled());
    expect(onChanged).toHaveBeenCalledWith("source");
  });

  it("hides source clearing after the source body is unavailable", () => {
    render(<RetrospectiveLifecycleActions retrospective={{ ...retrospective("active"), activeSourceAvailable: false }} onChanged={vi.fn()} onError={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "清除原文" })).toBeNull();
  });

  it("archives without requiring destructive confirmation text", async () => {
    const onChanged = vi.fn();
    render(<RetrospectiveLifecycleActions retrospective={retrospective("active")} onChanged={onChanged} onError={vi.fn()} />);
    fireEvent.click(screen.getByText("更多操作"));
    fireEvent.click(screen.getByRole("button", { name: "归档" }));
    await waitFor(() => expect(api.transitionRetrospective).toHaveBeenCalledWith("w1", expect.objectContaining({ id: "retro-1" }), "archive"));
    expect(screen.queryByLabelText("永久删除确认")).toBeNull();
  });

  it("shows private deletion impact and preserves external assets", async () => {
    const onChanged = vi.fn();
    render(<RetrospectiveLifecycleActions retrospective={retrospective("recycled")} onChanged={onChanged} onError={vi.fn()} />);
    fireEvent.click(screen.getByText("更多操作"));
    fireEvent.click(screen.getByRole("button", { name: "永久删除" }));

    expect(await screen.findByText(/1 份原文、2 个整理版本、3 次分析和 5 个行动项/)).toBeVisible();
    expect(screen.getByText(/复习题、个人画像、项目经历和知识库的内容不会被删除/)).toBeVisible();
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "永久删除" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("永久删除确认"), { target: { value: "永久删除" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(api.permanentlyDeleteRetrospective).toHaveBeenCalled());
    expect(onChanged).toHaveBeenCalledWith("deleted");
  });
});
