import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    const onPermanentDelete = vi.fn();
    const onPermanentDeleteVersion = vi.fn();
    const view = render(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={detail} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={onSelectVersion} onRetry={onRetry} onArchive={onArchive} onRestore={onRestore} onSetPrimary={onSetPrimary} onPermanentDelete={onPermanentDelete} onPermanentDeleteVersion={onPermanentDeleteVersion} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByLabelText("简历处理进度")).toHaveTextContent("上传");
    expect(screen.getByLabelText("简历处理进度")).toHaveTextContent("生成确认清单");
    expect(screen.getByRole("alert")).toHaveTextContent("文本提取失败");
    fireEvent.click(screen.getByRole("button", { name: "继续提取文本" }));
    expect(onRetry).toHaveBeenCalledWith("v2");
    fireEvent.keyDown(screen.getByRole("button", { name: /v2 resume-v2.pdf/ }), { key: "ArrowDown" });
    expect(onSelectVersion).toHaveBeenCalledWith("v1");
    fireEvent.click(screen.getByRole("button", { name: "设为当前版本" }));
    expect(onSetPrimary).toHaveBeenCalledWith(material, "v2");
    fireEvent.click(screen.getByRole("button", { name: "归档简历" }));
    expect(onArchive).toHaveBeenCalledWith(material);
    expect(screen.getByRole("button", { name: "删除当前版本 v2" })).toBeDisabled();
    expect(screen.getByText("请先处理全部 2 条待确认信息，再删除任一简历版本")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "永久删除整份简历（含 2 个版本）" }));
    expect(onPermanentDelete).toHaveBeenCalledWith(material);
    const archived = { ...material, lifecycleStatus: "archived" } satisfies ProfileMaterial;
    view.rerender(<ResumeVersions materials={[archived]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={{ ...detail, proposalCounts: { ...detail.proposalCounts, pending: 0 } }} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={onSelectVersion} onRetry={onRetry} onArchive={onArchive} onRestore={onRestore} onSetPrimary={onSetPrimary} onPermanentDelete={onPermanentDelete} onPermanentDeleteVersion={onPermanentDeleteVersion} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "恢复简历" }));
    expect(onRestore).toHaveBeenCalledWith(archived);
    fireEvent.click(screen.getByRole("button", { name: "删除当前版本 v2" }));
    expect(onPermanentDeleteVersion).toHaveBeenCalledWith(archived, expect.objectContaining({ id: "v2" }));
  });

  it("explains what happens while profile suggestions are generated", () => {
    const extracting = {
      ...detail,
      processingStatus: "extracting",
      stages: [
        { key: "uploaded", label: "已上传", status: "completed" },
        { key: "parsing", label: "提取文本", status: "completed" },
        { key: "parsed", label: "隐私处理", status: "completed" },
        { key: "extracting", label: "生成画像建议", status: "active" },
        { key: "ready", label: "等待确认", status: "pending" },
      ],
      evidencePage: { ...detail.evidencePage, total: 12 },
      execution: { ...detail.execution, status: "running", errorCode: null },
    } satisfies ProfileMaterialVersionDetail;

    render(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={extracting} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("正在根据 12 个内容区块整理画像建议");
    expect(screen.getByRole("status")).toHaveTextContent("技能、项目、工作经历、教育经历和成果");
    expect(screen.getByRole("status")).toHaveTextContent("停止后会保留文件、文本和已完成步骤");
  });

  it("focuses and highlights the processing panel when the background entry requests it", async () => {
    const view = render(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={detail} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    view.rerender(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={detail} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} processFocusRequest={1} />);

    const panel = screen.getByRole("region", { name: "简历处理过程" });
    await waitFor(() => {
      expect(panel).toHaveFocus();
      expect(panel).toHaveAttribute("data-highlighted", "true");
    });
  });

  it("explains that the only version must be removed through whole-resume deletion", () => {
    render(<ResumeVersions materials={[{ ...material, versionCount: 1 }]} versions={[versions[1]]} selectedMaterialId="m1" selectedVersionId="v1" detail={{ ...detail, ...versions[1], proposalCounts: { ...detail.proposalCounts, pending: 0 } }} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByText("简历处理完成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除当前版本 v1" })).toBeDisabled();
    expect(screen.getByText("这是唯一版本，如需清除请删除整份简历")).toBeInTheDocument();
  });

  it("shows the real number of profile items waiting for confirmation", () => {
    render(<ResumeVersions materials={[material]} versions={[versions[1]]} selectedMaterialId="m1" selectedVersionId="v1" detail={{ ...detail, ...versions[1] }} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByText("2 条简历要点待确认")).toBeInTheDocument();
  });

  it("blocks every version deletion while the workspace still has pending profile information", () => {
    render(<ResumeVersions materials={[material]} versions={versions} selectedMaterialId="m1" selectedVersionId="v2" detail={{ ...detail, proposalCounts: { ...detail.proposalCounts, pending: 0 } }} pendingProposalCount={7} busy={false} onSelectMaterial={vi.fn()} onSelectVersion={vi.fn()} onRetry={vi.fn()} onArchive={vi.fn()} onRestore={vi.fn()} onSetPrimary={vi.fn()} onPermanentDelete={vi.fn()} onPermanentDeleteVersion={vi.fn()} onOpenEvidence={vi.fn()} onAddVersion={vi.fn()} />);

    expect(screen.getByRole("button", { name: "删除当前版本 v2" })).toBeDisabled();
    expect(screen.getByText("请先处理全部 7 条待确认信息，再删除任一简历版本")).toBeInTheDocument();
  });
});
