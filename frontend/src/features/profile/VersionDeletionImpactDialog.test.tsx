import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VersionDeletionImpactDialog } from "./VersionDeletionImpactDialog";
import type { MaterialVersionDeletionPreview, ProfileMaterial, ProfileMaterialVersionDetail } from "./profileTypes";

const api = vi.hoisted(() => ({
  previewMaterialVersionDeletion: vi.fn(),
  permanentlyDeleteMaterialVersion: vi.fn(),
}));
vi.mock("./profileApi", () => api);

const material: ProfileMaterial = {
  id: "m1", workspaceId: "w1", type: "resume", title: "主简历", primaryRole: "resume",
  currentVersionId: "v2", lifecycleStatus: "active", version: 3, versionCount: 2,
  latestProcessingStatus: "ready", createdAt: "", updatedAt: "",
};
const version = {
  id: "v2", materialId: "m1", versionNumber: 2, sourceType: "upload", fileName: "resume-v2.pdf",
  mimeType: "application/pdf", processingStatus: "ready", canRetry: false, createdAt: "",
  stages: [], material, evidencePage: { items: [], offset: 0, limit: 50, total: 2, hasMore: false },
  proposalCounts: { total: 0, pending: 0, accepted: 0, rejected: 0, superseded: 0 },
  execution: null,
} satisfies ProfileMaterialVersionDetail;
const preview: MaterialVersionDeletionPreview = {
  deletionPlanId: "dp-v2", materialId: "m1", materialVersion: 3, expiresAt: "2099-07-22T12:00:00+00:00",
  versionId: "v2", versionNumber: 2, isCurrentVersion: true, affectedEvidenceCount: 2,
  affectedClaims: [{
    claimId: "c1", claimType: "skill", claimVersion: 2, claimVersionId: "cv1",
    supportStatus: "supported", value: { name: "FastAPI", description: "负责接口与任务编排" },
    affectedEvidenceIds: ["e1"], remainingEvidenceIds: [], selectionIds: [],
  }],
  unsupportedClaimIds: ["c1"], publicationSelectionIds: [], activePublicationIds: [],
  pendingProposalCount: 0,
  replacementVersions: [{ id: "v1", versionNumber: 1, fileName: "resume-v1.pdf" }],
};

describe("VersionDeletionImpactDialog", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    api.previewMaterialVersionDeletion.mockResolvedValue(preview);
    api.permanentlyDeleteMaterialVersion.mockResolvedValue({ planId: "dp-v2", status: "completed", items: [] });
  });

  it("requires a replacement when deleting the current version", async () => {
    const onDeleted = vi.fn();
    render(<VersionDeletionImpactDialog open workspaceId="w1" material={material} version={version} onClose={vi.fn()} onDeleted={onDeleted} />);

    expect(await screen.findByRole("dialog")).toHaveTextContent("只删除 v2");
    expect(screen.getByLabelText("删除后使用的当前版本")).toHaveValue("v1");
    const remove = screen.getByRole("button", { name: "删除此版本" });
    expect(remove).toBeDisabled();
    fireEvent.change(screen.getByLabelText("输入“删除此版本”确认"), { target: { value: "删除此版本" } });
    fireEvent.click(remove);

    await waitFor(() => expect(api.permanentlyDeleteMaterialVersion).toHaveBeenCalledWith(
      "w1",
      material,
      preview,
      "v1",
      [{ claimId: "c1", action: "retain_unsupported" }],
      "not_applicable",
    ));
    expect(onDeleted).toHaveBeenCalledWith(expect.anything(), "v1", {
      deletedClaimTitles: [],
      fileName: "resume-v2.pdf",
      retainedSupportedClaimTitles: [],
      retainedUnsupportedClaimTitles: ["FastAPI"],
      versionNumber: 2,
    });
  });

  it("does not request a replacement for a historical version", async () => {
    api.previewMaterialVersionDeletion.mockResolvedValueOnce({
      ...preview,
      versionId: "v1",
      versionNumber: 1,
      isCurrentVersion: false,
    });
    render(<VersionDeletionImpactDialog open workspaceId="w1" material={material} version={{ ...version, id: "v1", versionNumber: 1 }} onClose={vi.fn()} onDeleted={vi.fn()} />);

    await screen.findByRole("dialog");
    expect(screen.queryByLabelText("删除后使用的当前版本")).toBeNull();
  });

  it("selects affected claims for batch handling and reveals their details", async () => {
    const projectClaim = {
      ...preview.affectedClaims[0],
      claimId: "c2",
      claimType: "project",
      claimVersionId: "cv2",
      value: {
        name: "面试准备 Agent",
        description: "基于可恢复工作流整理面试资料",
        tech_stack: ["FastAPI", "LangGraph"],
      },
    };
    api.previewMaterialVersionDeletion.mockResolvedValueOnce({
      ...preview,
      affectedClaims: [...preview.affectedClaims, projectClaim],
      unsupportedClaimIds: ["c1", "c2"],
    });
    render(<VersionDeletionImpactDialog open workspaceId="w1" material={material} version={version} onClose={vi.fn()} onDeleted={vi.fn()} />);

    const selectAll = await screen.findByRole("checkbox", { name: "全选受影响简历要点" });
    fireEvent.click(selectAll);
    expect(screen.getByText("已选择 2 条")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("批量更改所选处理方式"), { target: { value: "delete" } });
    expect(screen.getByLabelText("FastAPI 的处理方式")).toHaveValue("delete");
    expect(screen.getByLabelText("面试准备 Agent 的处理方式")).toHaveValue("delete");

    fireEvent.click(screen.getByRole("button", { name: "查看 面试准备 Agent 详情" }));
    expect(screen.getByText("基于可恢复工作流整理面试资料")).toBeInTheDocument();
    expect(screen.getByText("FastAPI、LangGraph")).toBeInTheDocument();
  });
});
