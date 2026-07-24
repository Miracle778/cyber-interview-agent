import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ProfileToolStage } from "./ProfileToolStage";

describe("ProfileToolStage", () => {
  afterEach(cleanup);

  it("renders a safe lifecycle label without raw tool content", () => {
    render(<ProfileToolStage event={{ id: 1, type: "agent.tool.completed", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "read_personal_evidence", secret: "private resume text" } }} />);
    expect(screen.getByText("已查看简历原文")).toBeInTheDocument();
    expect(screen.queryByText(/private resume text/)).not.toBeInTheDocument();
  });

  it("turns internal tool failure into an actionable user message", () => {
    render(<ProfileToolStage event={{ id: 2, type: "agent.tool.failed", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "get_profile_claims", errorCode: "agent_execution_failed" } }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("无法查看已确认信息，请重试");
    expect(screen.queryByText(/agent_execution_failed/)).not.toBeInTheDocument();
  });

  it("uses a plain-language label for batch evidence reads", () => {
    render(<ProfileToolStage event={{
      id: 2,
      type: "agent.tool.completed",
      sessionId: "s1",
      executionId: "r1",
      timestamp: "now",
      payload: { toolName: "read_personal_evidence_batch", toolCallId: "c2" },
    }} />);
    expect(screen.getByRole("status")).toHaveTextContent("已查看简历原文");
  });

  it("stops a stale spinner when its Execution is no longer active", () => {
    render(<ProfileToolStage executionActive={false} event={{ id: 3, type: "agent.tool.started", sessionId: "s", executionId: "e", timestamp: "now", payload: { toolName: "search_personal_materials" } }} />);
    expect(screen.getByRole("status")).toHaveTextContent("已停止查找简历内容");
    expect(document.querySelector(".spin")).toBeNull();
  });
});
