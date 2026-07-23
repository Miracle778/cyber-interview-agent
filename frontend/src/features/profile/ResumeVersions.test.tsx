import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResumeVersions } from "./ResumeVersions";
import type { ProfileMaterial, ProfileMaterialVersion, ProfileMaterialVersionDetail } from "./profileTypes";

const material: ProfileMaterial = {
  id: "m1", workspaceId: "w1", type: "resume", title: "后端工程师简历", primaryRole: "resume", currentVersionId: "v1",
  lifecycleStatus: "active", version: 2, versionCount: 2, latestProcessingStatus: "parse_failed", createdAt: "2026-07-20T10:00:00Z", updatedAt: "2026-07-20T10:20:00Z",
};
const versions: ProfileMaterialVersion[] = [
  { id: "v2", materialId: "m1", versionNumber: 2, sourceType: "upload", fileName: "resume-v2.pdf", mimeType: "application/pdf", processingStatus: "parse_failed", canRetry: true, createdAt: "2026-07-20T10:20:00Z", stages: [
    { key: "uploaded", label: "已上传", status: "completed" }, { key: "parsing", label: "解析材料", status: "failed" }, { key: "parsed", label: "文本已解析", status: "pending" }, { key: "extracting", label: "提取画像", status: "pending" }, { key: "ready", label: "处理完成", status: "pending" },
  ] },
  { id: "v1", materialId: "m1", versionNumber: 1, sourceType: "upload", fileName: "resume-v1.pdf", mimeType: "application/pdf", processingStatus: "ready", canRetry: false, createdAt: "2026-07-19T10:20:00Z", stages: [] },
];
const detail = { ...versions[0], material, evidencePage: { items: [], offset: 0, limit: 50, total: 0, hasMore: false }, proposalCounts: { total: 3, pending: 2, accepted: 1, rejected: 0, superseded: 0 }, execution: { id: "e1", status: "failed", errorCode: "profile_parse_failed", createdAt: "", startedAt: null, finishedAt: null, retryable: true } } satisfies ProfileMaterialVersionDetail;

describe("ResumeVersions", () => {
  afterEach(cleanup);
  it("supports keyboard version selection, deterministic stages, retry and lifecycle actions", () => {
    const onSelectVersion = vi.fn();
    const onRetry = vi.fn();
    const onArchive = vi.fn();
    const onRestore = vi.fn();
    const onSetPrimary = vi.fn();
    const view = render(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={detail} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={onSelectVersion} onRetry={onRetry} onArchive={onArchive} onRestore={onRestore} onSetPrimary={onSetPrimary} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByLabelText("材料处理进度")).toHaveTextContent("上传");
    expect(screen.getByLabelText("材料处理进度")).toHaveTextContent("等待审核");
    expect(screen.getByRole("alert")).toHaveTextContent("文本提取失败");
    fireEvent.click(screen.getByRole("button", { name: "重试文本提取" }));
    expect(onRetry).toHaveBeenCalledWith("v2");
    fireEvent.keyDown(screen.getByRole("button", { name: /v2 resume-v2.pdf/ }), { key: "ArrowDown" });
    expect(onSelectVersion).toHaveBeenCalledWith("v1");
    fireEvent.click(screen.getByRole("button", { name: "设为当前版本" }));
    expect(onSetPrimary).toHaveBeenCalledWith(material, "v2");
    fireEvent.click(screen.getByRole("button", { name: "归档材料" }));
    expect(onArchive).toHaveBeenCalledWith(material);
    const archived = { ...material, lifecycleStatus: "archived" } satisfies ProfileMaterial;
    view.rerender(<ResumeVersions materials={[archived]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={detail} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={onSelectVersion} onRetry={onRetry} onArchive={onArchive} onRestore={onRestore} onSetPrimary={onSetPrimary} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "恢复材料" }));
    expect(onRestore).toHaveBeenCalledWith(archived);
  });
});
