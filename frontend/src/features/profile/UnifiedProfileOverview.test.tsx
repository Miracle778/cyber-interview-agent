import { cleanup, render, screen } from "@testing-library/react";
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
    />);

    expect(screen.queryByText(/缺少来源依据/)).not.toBeInTheDocument();
    screen.getByRole("button", { name: "1 条相关内容待核对" }).click();
    expect(onOpenSupportReview).toHaveBeenCalledWith("related");
    expect(screen.getByRole("button", { name: "Nginx 灰度发布，相关内容待核对" })).toBeInTheDocument();
  });
});
