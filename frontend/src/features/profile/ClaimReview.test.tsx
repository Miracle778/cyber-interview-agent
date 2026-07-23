import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClaimReview } from "./ClaimReview";
import type { ProfileClaimWorkspace } from "./profileTypes";

const api = vi.hoisted(() => ({ decideClaimProposal: vi.fn(), batchDecideClaimProposals: vi.fn() }));
vi.mock("./profileApi", () => api);

const evidence = { id: "e1", materialVersionId: "mv1", locator: { lineStart: 11, lineEnd: 13 }, startOffset: 1, endOffset: 9, excerpt: "负责 Agent 工作流设计", sensitivity: "private", createdAt: "2026-07-22" };
const currentVersion = { id: "cv1", claimId: "c1", version: 2, value: { role: "后端开发" }, status: "confirmed", supportStatus: "supported", evidenceIds: ["e1"], source: "material", expectedPreviousVersion: 1, createdAt: "", confirmedAt: "" };
const proposals = [
  { id: "p1", proposalType: "update", targetClaimId: "c1", baseClaimVersionId: "cv1", proposedValue: { role: "核心后端开发" }, reason: "材料显示职责扩大", status: "pending", evidence: [evidence], decidedAt: null, createdAt: "" },
  { id: "p2", proposalType: "create", targetClaimId: null, baseClaimVersionId: null, proposedValue: { skill: "LangGraph" }, reason: "项目中多次使用", status: "pending", evidence: [evidence], decidedAt: null, createdAt: "" },
] satisfies ProfileClaimWorkspace["proposals"];
const snapshot: ProfileClaimWorkspace = { workspaceId: "w1", profileVersion: "pv1", claims: [{ id: "c1", claimType: "project", version: 2, currentVersion, versions: [currentVersion], proposals: [proposals[0]], conflicts: [{ id: "x1", proposalId: "p1", conflictingClaimVersionId: "cv2", createdAt: "" }], evidence: [evidence], createdAt: "", updatedAt: "" }], proposals };

describe("ClaimReview", () => {
  afterEach(cleanup);
  beforeEach(() => { vi.clearAllMocks(); api.decideClaimProposal.mockResolvedValue({ proposalId: "p1", status: "accepted" }); });

  it("filters the queue and exposes conflict, side-by-side diff and evidence navigation without color-only cues", async () => {
    const onOpenEvidence = vi.fn();
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={vi.fn()} onOpenEvidence={onOpenEvidence} onOpenDeletion={vi.fn()} />);
    expect(screen.getAllByText("存在冲突").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "当前内容与建议内容对比" })).toHaveTextContent("后端开发");
    expect(screen.getByRole("region", { name: "当前内容与建议内容对比" })).toHaveTextContent("核心后端开发");
    expect(screen.queryByText(/lineStart|lineEnd/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /查看第 11–13 行原文位置/ }));
    expect(onOpenEvidence).toHaveBeenCalledWith(evidence);
    fireEvent.change(screen.getByLabelText("按分类筛选"), { target: { value: "new" } });
    expect(screen.getByRole("button", { name: /项目中多次使用/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /材料显示职责扩大/ })).toBeNull();
  });

  it("keeps batch choices visible until success and preserves the conflicting item", async () => {
    const refresh = vi.fn();
    api.batchDecideClaimProposals.mockResolvedValue({ items: [{ proposalId: "p1", status: "completed", result: {}, errorCode: null, retryable: false }, { proposalId: "p2", status: "conflict", result: null, errorCode: "profile_claim_version_conflict", retryable: true }] });
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={refresh} onOpenEvidence={vi.fn()} onOpenDeletion={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "加入批量处理" }));
    fireEvent.click(screen.getByRole("button", { name: /项目中多次使用/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "加入批量处理" }));
    expect(screen.getByText(/已选择/)).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("button", { name: "批量确认" }));
    await waitFor(() => expect(api.batchDecideClaimProposals).toHaveBeenCalled());
    expect(screen.getByText(/已选择/)).toHaveTextContent("1");
    expect(screen.getByRole("status")).toHaveTextContent("冲突项已刷新并保留选择");
    expect(refresh).toHaveBeenCalled();
  });

  it("submits a single explicit decision with the current claim version", async () => {
    const refresh = vi.fn();
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={refresh} onOpenEvidence={vi.fn()} onOpenDeletion={vi.fn()} />);
    const detail = screen.getByRole("main");
    fireEvent.click(within(detail).getByRole("button", { name: "确认此项" }));
    await waitFor(() => expect(api.decideClaimProposal).toHaveBeenCalledWith("w1", "p1", "accepted", 2));
    expect(refresh).toHaveBeenCalled();
  });
});
