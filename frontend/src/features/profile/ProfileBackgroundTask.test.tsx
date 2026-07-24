import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileBackgroundTask } from "./ProfileBackgroundTask";
import type { ProfileMaterialVersionDetail } from "./profileTypes";

const detail = {
  id: "v1", materialId: "m1", versionNumber: 1, sourceType: "upload", fileName: "resume.md",
  mimeType: "text/markdown", processingStatus: "extracting", canRetry: false, createdAt: "2026-07-24T08:00:00Z",
  stages: [{ key: "extracting", label: "生成画像建议", status: "active" }],
  material: { id: "m1", workspaceId: "w1", type: "resume", title: "简历", primaryRole: "resume", currentVersionId: "v1", lifecycleStatus: "active", version: 1, versionCount: 1, latestProcessingStatus: "extracting", createdAt: "", updatedAt: "" },
  evidencePage: { items: [], offset: 0, limit: 100, total: 13, hasMore: false },
  proposalCounts: { total: 0, pending: 0, accepted: 0, rejected: 0, superseded: 0 },
  execution: { id: "e1", status: "running", errorCode: null, createdAt: "", startedAt: "2026-07-24T08:00:00Z", finishedAt: null, retryable: false },
} satisfies ProfileMaterialVersionDetail;

describe("ProfileBackgroundTask", () => {
  afterEach(cleanup);

  it("shows honest progress and exposes stop without inventing a percentage", () => {
    const onStop = vi.fn();
    render(<ProfileBackgroundTask detail={detail} stopping={false} continuing={false} onOpen={vi.fn()} onStop={onStop} onContinue={vi.fn()} onOpenPending={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("生成画像建议");
    expect(screen.getByRole("status")).toHaveTextContent("已识别 13 个内容区块");
    expect(screen.queryByText(/%/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "停止整理" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("turns a completed task into a clear review entry", () => {
    const onOpenPending = vi.fn();
    render(<ProfileBackgroundTask detail={{ ...detail, processingStatus: "ready", proposalCounts: { ...detail.proposalCounts, pending: 27 }, execution: { ...detail.execution!, status: "completed" } }} stopping={false} continuing={false} onOpen={vi.fn()} onStop={vi.fn()} onContinue={vi.fn()} onOpenPending={onOpenPending} />);
    expect(screen.getByRole("status")).toHaveTextContent("已整理出 27 条待确认信息");
    const reviewButton = screen.getByRole("button", { name: "确认这 27 条" });
    expect(reviewButton).toBeEnabled();
    fireEvent.click(reviewButton);
    expect(onOpenPending).toHaveBeenCalledOnce();
  });
});
