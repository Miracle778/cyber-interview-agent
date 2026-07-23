import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ProfileToolStage } from "./ProfileToolStage";

describe("ProfileToolStage", () => {
  afterEach(cleanup);

  it("renders a safe lifecycle label without raw tool content", () => {
    render(<ProfileToolStage event={{ id: 1, type: "agent.tool.completed", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "read_personal_evidence", secret: "private resume text" } }} />);
    expect(screen.getByText("已读取证据")).toBeInTheDocument();
    expect(screen.queryByText(/private resume text/)).not.toBeInTheDocument();
  });

  it("turns internal tool failure into an actionable user message", () => {
    render(<ProfileToolStage event={{ id: 2, type: "agent.tool.failed", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "get_profile_claims", errorCode: "agent_execution_failed" } }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("无法读取已确认画像，请重试");
    expect(screen.queryByText(/agent_execution_failed/)).not.toBeInTheDocument();
  });

  it("stops a stale spinner when its Execution is no longer active", () => {
    render(<ProfileToolStage executionActive={false} event={{ id: 3, type: "agent.tool.started", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "search_personal_materials" } }} />);
    expect(screen.getByRole("status")).toHaveTextContent("已停止检索个人材料");
    expect(document.querySelector(".spin")).toBeNull();
  });
});
