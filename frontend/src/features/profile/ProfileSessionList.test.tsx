import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentExecutionStatus, AgentSession } from "../agent/agentTypes";
import { ProfileSessionList } from "./ProfileSessionList";

function session(
  id: string,
  title: string,
  latestExecutionStatus: AgentExecutionStatus | null,
  pendingActionCount = 0,
): AgentSession {
  return {
    id,
    workspaceId: "w1",
    kind: "profile.manage",
    title,
    status: "completed",
    createdAt: "2026-07-28T08:00:00Z",
    updatedAt: "2026-07-28T08:00:00Z",
    latestExecutionId: latestExecutionStatus ? `${id}-run` : null,
    latestExecutionStatus,
    pendingActionCount,
  };
}

describe("ProfileSessionList", () => {
  afterEach(cleanup);

  it("filters by latest execution and pending actions instead of session lifecycle", () => {
    render(<ProfileSessionList
      sessions={[
        session("running", "正在检查项目", "running"),
        session("failed", "失败后待处理", "failed"),
        session("approval", "有建议待确认", "completed", 1),
        session("done", "已完成会话", "completed"),
      ]}
      archived={[]}
      loading={false}
      creating={false}
      mutatingId={null}
      showRecycleBin={false}
      onShowRecycleBin={vi.fn()}
      onCreate={vi.fn()}
      onOpen={vi.fn()}
      onArchive={vi.fn()}
      onRestore={vi.fn()}
      onDeletePermanently={vi.fn()}
    />);

    fireEvent.click(screen.getByRole("button", { name: "正在运行 1" }));
    expect(screen.getByText("正在检查项目")).toBeInTheDocument();
    expect(screen.queryByText("失败后待处理")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "需要处理 2" }));
    expect(screen.getByText("失败后待处理")).toBeInTheDocument();
    expect(screen.getByText("有建议待确认")).toBeInTheDocument();
    expect(screen.queryByText("已完成会话")).not.toBeInTheDocument();
  });
});
