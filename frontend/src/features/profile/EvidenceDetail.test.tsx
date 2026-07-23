import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceDetail } from "./EvidenceDetail";

describe("EvidenceDetail", () => {
  afterEach(cleanup);
  it("shows safe source locators and lets keyboard users return", () => {
    const onBack = vi.fn();
    render(<EvidenceDetail materialTitle="后端工程师简历" versionNumber={4} evidence={{ id: "ev1", materialVersionId: "v4", locator: { page: 2, section: "项目经历", block: "Cyber Interview Agent" }, startOffset: 120, endOffset: 360, excerpt: "基于 LangGraph 设计多 Agent 工作流，支持恢复与审批发布。", sensitivity: "private", createdAt: "2026-07-20T10:00:00Z" }} onBack={onBack} />);
    expect(screen.getByRole("heading", { level: 2, name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getAllByText("第 2 页 · 项目经历")).toHaveLength(3);
    expect(screen.getByText(/基于 LangGraph/)).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "返回版本详情" }), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "返回版本详情" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
