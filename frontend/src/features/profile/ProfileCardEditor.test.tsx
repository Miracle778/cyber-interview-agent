import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileCardEditor } from "./ProfileCardEditor";
import type { UnifiedProfileCard } from "./profileTypes";

describe("ProfileCardEditor", () => {
  afterEach(cleanup);

  it("explains related resume evidence before the user edits the claim", () => {
    const card: UnifiedProfileCard = {
      claimId: "c1",
      claimVersionId: "cv1",
      category: "skill",
      version: 1,
      supportStatus: "related",
      supportSummary: "剩余简历中发现相关描述，需要你核对是否能作为这条资料的依据",
      supportEvidence: [{
        evidenceId: "e1",
        materialTitle: "主投版简历",
        versionNumber: 1,
        section: "项目经历",
        excerpt: "负责限流熔断、灰度发布和故障演练",
        relation: "related",
      }],
      title: "Nginx 灰度发布",
      subtitle: null,
      value: { name: "Nginx 灰度发布" },
      sources: [{ sourceKind: "resume_extraction", label: "原来源已删除，本人保留", status: "source_deleted" }],
      linkedTo: [],
      usedIn: [],
    };

    render(<ProfileCardEditor
      card={card}
      busy={false}
      error={null}
      onSave={vi.fn()}
      onDelete={vi.fn()}
      onCancel={vi.fn()}
    />);

    expect(screen.getByText("相关内容待核对")).toBeInTheDocument();
    expect(screen.getByText("主投版简历 v1 · 项目经历")).toBeInTheDocument();
    expect(screen.getByText("负责限流熔断、灰度发布和故障演练")).toBeInTheDocument();
  });
});
