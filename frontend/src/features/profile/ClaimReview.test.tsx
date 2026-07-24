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
  { id: "p2", proposalType: "create", targetClaimId: null, baseClaimVersionId: null, proposedValue: { category: "skill", skill: "LangGraph" }, reason: "Evidence 显示项目中多次使用", status: "pending", evidence: [evidence], decidedAt: null, createdAt: "" },
] satisfies ProfileClaimWorkspace["proposals"];
const snapshot: ProfileClaimWorkspace = { workspaceId: "w1", profileVersion: "pv1", claims: [{ id: "c1", claimType: "project", version: 2, currentVersion, versions: [currentVersion], proposals: [proposals[0]], conflicts: [{ id: "x1", proposalId: "p1", conflictingClaimVersionId: "cv2", createdAt: "" }], evidence: [evidence], createdAt: "", updatedAt: "" }], proposals };

describe("ClaimReview", () => {
  afterEach(cleanup);
  beforeEach(() => { vi.clearAllMocks(); api.decideClaimProposal.mockResolvedValue({ proposalId: "p1", status: "accepted" }); });

  it("filters the queue and exposes conflict, user-facing preview and evidence navigation without color-only cues", async () => {
    const onOpenEvidence = vi.fn();
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={vi.fn()} onOpenEvidence={onOpenEvidence} />);
    expect(screen.queryByRole("button", { name: "永久删除材料" })).toBeNull();
    expect(screen.getAllByText("需要核对").length).toBeGreaterThan(0);
    expect(screen.getByText(/与之前记录不同/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "确认后个人画像会显示的内容" })).toHaveTextContent("原来：后端开发");
    expect(screen.getByRole("region", { name: "确认后个人画像会显示的内容" })).toHaveTextContent("核心后端开发");
    expect(screen.queryByText(/lineStart|lineEnd/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /查看第 11–13 行原文位置/ }));
    expect(onOpenEvidence).toHaveBeenCalledWith(evidence);
    fireEvent.change(screen.getByLabelText("按分类筛选"), { target: { value: "skill" } });
    expect(screen.getByRole("button", { name: /简历原文.*显示项目中多次使用/ })).toBeInTheDocument();
    expect(screen.queryByText(/Evidence/)).toBeNull();
    expect(screen.queryByRole("button", { name: /材料显示职责扩大/ })).toBeNull();
  });

  it("keeps batch choices visible until success and preserves the conflicting item", async () => {
    const refresh = vi.fn();
    api.batchDecideClaimProposals.mockResolvedValue({ items: [{ proposalId: "p2", status: "conflict", result: null, errorCode: "profile_claim_version_conflict", retryable: true }] });
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={refresh} onOpenEvidence={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /简历原文.*显示项目中多次使用/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 LangGraph" }));
    expect(screen.getByText(/已选择/)).toHaveTextContent("1");
    fireEvent.click(screen.getByRole("button", { name: "批量确认" }));
    await waitFor(() => expect(api.batchDecideClaimProposals).toHaveBeenCalled());
    expect(screen.getByText(/已选择/)).toHaveTextContent("1");
    expect(screen.getByRole("status")).toHaveTextContent("发生变化或保存失败");
    expect(refresh).toHaveBeenCalled();
  });

  it("submits a single explicit decision with the current claim version", async () => {
    const refresh = vi.fn();
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={refresh} onOpenEvidence={vi.fn()} />);
    const detail = screen.getByRole("main");
    fireEvent.click(within(detail).getByRole("button", { name: "信息准确" }));
    await waitFor(() => expect(api.decideClaimProposal).toHaveBeenCalledWith("w1", "p1", "accepted", 2));
    expect(refresh).toHaveBeenCalled();
  });

  it("shows the count for the selected status instead of a stale pending count", () => {
    const acceptedProposal = { ...proposals[0], id: "p-accepted", status: "accepted" as const };
    render(<ClaimReview
      workspaceId="w1"
      snapshot={{ ...snapshot, proposals: [...proposals, acceptedProposal] }}
      onRefresh={vi.fn()}
      onOpenEvidence={vi.fn()}
    />);
    expect(screen.getByText("条待确认").closest("span")).toHaveTextContent("2 条待确认");
    fireEvent.change(screen.getByLabelText("按状态筛选"), { target: { value: "accepted" } });
    expect(screen.getByText("条已确认").closest("span")).toHaveTextContent("1 条已确认");
  });

  it("summarizes safe and excluded items before one-click confirmation", () => {
    render(<ClaimReview workspaceId="w1" snapshot={snapshot} onRefresh={vi.fn()} onOpenEvidence={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "一键确认当前可靠信息" }));
    const dialog = screen.getByRole("dialog", { name: "确认当前筛选中的可靠信息" });
    expect(dialog).toHaveTextContent("1条可以直接确认");
    expect(dialog).toHaveTextContent("1条需要逐项核对");
    expect(dialog).toHaveTextContent("不会被自动确认");
  });
});
