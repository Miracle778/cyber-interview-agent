import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UnifiedProfileOverview } from "./UnifiedProfileOverview";
import type { UnifiedProfile } from "./profileTypes";

describe("UnifiedProfileOverview", () => {
  afterEach(cleanup);

  it("makes retained claims with deleted evidence visible", () => {
    const onOpenSupportReview = vi.fn();
    const profile: UnifiedProfile = {
      workspaceId: "w1",
      profileVersion: "pv1",
      summary: null,
      directions: [],
      primaryDirectionClaimId: null,
      presentationVersion: 0,
      highlights: [],
      experiences: [],
      projects: [],
      skills: [{
        claimId: "c1",
        claimVersionId: "cv1",
        category: "skill",
        version: 1,
        title: "FastAPI",
        subtitle: null,
        value: { name: "FastAPI" },
        supportStatus: "unsupported",
        supportSummary: "当前简历中没有找到可以直接或相关核对的内容",
        supportEvidence: [],
        sources: [{ sourceKind: "resume_extraction", label: "简历提取", status: "active" }],
        linkedTo: [],
        usedIn: [],
      }],
      education: [],
      certifications: [],
      achievements: [],
      links: [],
      actionableGaps: [],
      pendingCount: 0,
      isUsable: true,
    };

    render(<UnifiedProfileOverview
      profile={profile}
      loading={false}
      onUpload={vi.fn()}
      onCreate={vi.fn()}
      onEdit={vi.fn()}
      onOpenPending={vi.fn()}
      onOpenSupportReview={onOpenSupportReview}
      onSetPrimaryDirection={vi.fn()}
      onCreateJobTarget={vi.fn()}
      onOpenReview={vi.fn()}
    />);

    screen.getByRole("button", { name: "1 条内容缺少直接依据" }).click();
    expect(onOpenSupportReview).toHaveBeenCalledWith("unsupported");
    expect(screen.getByRole("button", { name: "FastAPI，缺少直接依据" })).toBeInTheDocument();
  });

  it("separates related resume text from genuinely missing evidence", () => {
    const onOpenSupportReview = vi.fn();
    const profile: UnifiedProfile = {
      workspaceId: "w1",
      profileVersion: "pv2",
      summary: null,
      directions: [],
      primaryDirectionClaimId: null,
      presentationVersion: 0,
      highlights: [],
      experiences: [],
      projects: [],
      skills: [{
        claimId: "c2",
        claimVersionId: "cv2",
        category: "skill",
        version: 1,
        title: "Nginx 灰度发布",
        subtitle: null,
        value: { name: "Nginx 灰度发布" },
        supportStatus: "related",
        supportSummary: "剩余简历中发现相关描述，需要你核对是否能作为这条资料的依据",
        supportEvidence: [{
          evidenceId: "e2",
          materialTitle: "主投版简历",
          versionNumber: 1,
          section: "项目经历",
          excerpt: "负责限流熔断、灰度发布和故障演练",
          relation: "related",
        }],
        sources: [{ sourceKind: "resume_extraction", label: "原来源已删除，本人保留", status: "source_deleted" }],
        linkedTo: [],
        usedIn: [],
      }],
      education: [],
      certifications: [],
      achievements: [],
      links: [],
      actionableGaps: [],
      pendingCount: 0,
      isUsable: true,
    };

    render(<UnifiedProfileOverview
      profile={profile}
      loading={false}
      onUpload={vi.fn()}
      onCreate={vi.fn()}
      onEdit={vi.fn()}
      onOpenPending={vi.fn()}
      onOpenSupportReview={onOpenSupportReview}
      onSetPrimaryDirection={vi.fn()}
      onCreateJobTarget={vi.fn()}
      onOpenReview={vi.fn()}
    />);

    expect(screen.queryByText(/缺少来源依据/)).not.toBeInTheDocument();
    screen.getByRole("button", { name: "1 条相关内容待核对" }).click();
    expect(onOpenSupportReview).toHaveBeenCalledWith("related");
    expect(screen.getByRole("button", { name: "Nginx 灰度发布，相关内容待核对" })).toBeInTheDocument();
  });

  it("leads with career assets and exposes clear next actions", () => {
    const onCreateJobTarget = vi.fn();
    const onOpenReview = vi.fn();
    const profile: UnifiedProfile = {
      workspaceId: "w1",
      profileVersion: "pv3",
      summary: null,
      directions: [{
        claimId: "direction-1", claimVersionId: "direction-v1", category: "direction", version: 1,
        title: "Agent 开发工程师", subtitle: null, value: { description: "后端与 Agent 工程化" },
        supportStatus: "manual", supportSummary: "本人确认", supportEvidence: [], sources: [], linkedTo: [], usedIn: [],
      }],
      primaryDirectionClaimId: "direction-1",
      presentationVersion: 1,
      highlights: [], experiences: [],
      projects: [{
        claimId: "project-1", claimVersionId: "project-v1", category: "project", version: 1,
        title: "Agent 质量实验室", subtitle: "可恢复评估工作流", value: { tech_stack: ["FastAPI", "LangGraph"] },
        supportStatus: "supported", supportSummary: "有直接依据", supportEvidence: [], sources: [], linkedTo: [], usedIn: [],
      }],
      skills: [{
        claimId: "skill-1", claimVersionId: "skill-v1", category: "skill", version: 1,
        title: "FastAPI", subtitle: null, value: { name: "FastAPI" },
        supportStatus: "supported", supportSummary: "有直接依据", supportEvidence: [], sources: [], linkedTo: [], usedIn: [],
      }],
      education: [], certifications: [], achievements: [{
        claimId: "achievement-1", claimVersionId: "achievement-v1", category: "achievement", version: 1,
        title: "开源贡献", subtitle: null, value: { description: "参与 Agent 框架建设" },
        supportStatus: "supported", supportSummary: "有直接依据", supportEvidence: [], sources: [], linkedTo: [], usedIn: [],
      }], links: [], actionableGaps: [], pendingCount: 0, isUsable: true,
    };

    render(<UnifiedProfileOverview
      profile={profile}
      loading={false}
      onUpload={vi.fn()}
      onCreate={vi.fn()}
      onEdit={vi.fn()}
      onOpenPending={vi.fn()}
      onOpenSupportReview={vi.fn()}
      onSetPrimaryDirection={vi.fn()}
      onCreateJobTarget={onCreateJobTarget}
      onOpenReview={onOpenReview}
    />);

    expect(screen.getByRole("heading", { name: "Agent 开发工程师" })).toBeInTheDocument();
    expect(screen.getByText("1 个代表项目")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "待完善信息" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "证书与成果 1" }));
    expect(screen.getByRole("heading", { name: "成果" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "证书" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加证书（可选）" })).toBeInTheDocument();
    screen.getByRole("button", { name: "创建求职目标" }).click();
    screen.getByRole("button", { name: "进入自主复习" }).click();
    expect(onCreateJobTarget).toHaveBeenCalledOnce();
    expect(onOpenReview).toHaveBeenCalledOnce();
  });
});
