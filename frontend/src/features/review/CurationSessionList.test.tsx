import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurationSessionList } from "./CurationSessionList";
import type { CurationSession } from "./reviewTypes";

function session(id: string, stage: CurationSession["stage"], candidateCount: number, publishedCount: number): CurationSession {
  return {
    id,
    stage,
    title: `${id}.md`,
    sources: [{ id: `${id}-source`, filename: `${id}.md`, organizationState: "previously_curated" }],
    candidateCount,
    publishedCount,
    pendingCount: candidateCount - publishedCount,
  } as CurationSession;
}

describe("CurationSessionList", () => {
  afterEach(cleanup);

  it("explains and filters sessions that still need attention", () => {
    render(<CurationSessionList sessions={[session("active", "waiting_for_command", 4, 1), session("done", "completed", 3, 3), session("failed", "failed", 2, 0)]} candidateCount={9} publishedCount={4} onSelect={vi.fn()} onCreate={vi.fn()} onDelete={vi.fn()} onOpenLibrary={vi.fn()} />);

    const summary = screen.getByRole("button", { name: /待处理会话/ });
    expect(summary).toHaveAttribute("title", "包含排队、整理中、待确认和发布中的会话");
    expect(summary).toHaveTextContent("1");

    fireEvent.click(summary);
    const history = screen.getByRole("region", { name: "历史整理会话" });
    expect(within(history).getByRole("button", { name: /active\.md/ })).toBeInTheDocument();
    expect(within(history).queryByRole("button", { name: /done\.md/ })).toBeNull();
    expect(within(history).queryByRole("button", { name: /failed\.md/ })).toBeNull();
    expect(screen.getByText("仅显示待处理会话")).toBeInTheDocument();
  });

  it("opens the matching question-library scopes", () => {
    const onOpenLibrary = vi.fn();
    render(<CurationSessionList sessions={[session("active", "waiting_for_command", 4, 1)]} candidateCount={4} publishedCount={1} onSelect={vi.fn()} onCreate={vi.fn()} onDelete={vi.fn()} onOpenLibrary={onOpenLibrary} />);

    fireEvent.click(screen.getByRole("button", { name: /累计候选/ }));
    expect(onOpenLibrary).toHaveBeenLastCalledWith(null);
    fireEvent.click(screen.getByRole("button", { name: /已发布/ }));
    expect(onOpenLibrary).toHaveBeenLastCalledWith("published");
  });
});
