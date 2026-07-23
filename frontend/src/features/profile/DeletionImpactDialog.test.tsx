import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeletionImpactDialog } from "./DeletionImpactDialog";
import type { MaterialDeletionPreview, ProfileMaterial } from "./profileTypes";

const api = vi.hoisted(() => ({ previewMaterialDeletion: vi.fn(), permanentlyDeleteMaterial: vi.fn() }));
vi.mock("./profileApi", () => api);

const material: ProfileMaterial = { id: "m1", workspaceId: "w1", type: "resume", title: "主简历", primaryRole: "resume", currentVersionId: "v1", lifecycleStatus: "active", version: 3, versionCount: 1, latestProcessingStatus: "ready", createdAt: "", updatedAt: "" };
const preview: MaterialDeletionPreview = { deletionPlanId: "dp1", materialId: "m1", materialVersion: 3, expiresAt: "2099-07-22T12:00:00+00:00", affectedEvidenceCount: 4, affectedClaims: [{ claimId: "c1", claimType: "项目经历", claimVersion: 2, claimVersionId: "cv1", supportStatus: "supported", affectedEvidenceIds: ["e1"], remainingEvidenceIds: [], selectionIds: [] }], unsupportedClaimIds: ["c1"], publicationSelectionIds: ["s1"], activePublicationIds: ["pub1"] };

describe("DeletionImpactDialog", () => {
  afterEach(cleanup);
  beforeEach(() => { vi.clearAllMocks(); api.previewMaterialDeletion.mockResolvedValue(preview); api.permanentlyDeleteMaterial.mockResolvedValue({ planId: "dp1", status: "completed", items: [] }); });

  it("shows dependency impact, distinguishes permanent deletion and requires typed confirmation plus publication revoke", async () => {
    const onDeleted = vi.fn();
    render(<DeletionImpactDialog open workspaceId="w1" material={material} onClose={vi.fn()} onDeleted={onDeleted} />);
    expect(await screen.findByText("受影响证据")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveTextContent("归档可恢复；永久删除");
    const remove = screen.getByRole("button", { name: "永久删除" });
    expect(remove).toBeDisabled();
    fireEvent.change(screen.getByLabelText("输入“永久删除”确认"), { target: { value: "永久删除" } });
    expect(remove).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /同时撤销已发布的个人知识/ }));
    expect(remove).toBeEnabled();
    fireEvent.click(remove);
    await waitFor(() => expect(api.permanentlyDeleteMaterial).toHaveBeenCalledWith("w1", material, preview, [{ claimId: "c1", action: "retain_unsupported" }], "revoke"));
    expect(onDeleted).toHaveBeenCalled();
  });

  it("traps keyboard focus, closes with Escape and returns focus", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>打开删除</button><DeletionImpactDialog open={open} workspaceId="w1" material={material} onClose={() => setOpen(false)} onDeleted={vi.fn()} /></>;
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "打开删除" });
    opener.focus(); fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(screen.getByRole("button", { name: "关闭永久删除" })).toHaveFocus());
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });
});
