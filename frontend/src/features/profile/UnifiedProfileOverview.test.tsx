import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UnifiedProfileOverview } from "./UnifiedProfileOverview";
import type { UnifiedProfile } from "./profileTypes";

describe("UnifiedProfileOverview", () => {
  afterEach(cleanup);

  it("makes retained claims with deleted evidence visible", () => {
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
      onSetPrimaryDirection={vi.fn()}
    />);

    expect(screen.getByText("1 条内容缺少来源依据")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "FastAPI，依据不足" })).toBeInTheDocument();
  });
});
