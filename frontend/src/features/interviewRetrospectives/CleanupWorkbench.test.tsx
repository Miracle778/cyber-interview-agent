import { cleanup as cleanupDom, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CleanupWorkbench } from "./CleanupWorkbench";
import type { CleanupVersion } from "./retrospectiveTypes";

const cleanup: CleanupVersion = {
  id: "cleanup-1",
  retrospectiveId: "retro-1",
  sourceVersionId: "source-1",
  ordinal: 1,
  executionId: "execution-1",
  status: "review_pending",
  stage: "review_pending",
  controlIntent: null,
  confirmedAt: null,
  version: 3,
  createdAt: "2026-08-01 00:00:00",
  updatedAt: "2026-08-01 00:00:04",
  segments: [
    {
      id: "segment-1",
      ordinal: 1,
      speakerRole: "unknown",
      rawSpeakerLabel: "说话人 1",
      displayName: "待确认",
      body: "你为什么选择我们公司？",
      sourceStart: 0,
      sourceEnd: 12,
      confidence: 0.48,
      uncertaintyReason: "说话人标签不明确",
      ignored: false,
      version: 1,
    },
    {
      id: "segment-2",
      ordinal: 2,
      speakerRole: "candidate",
      rawSpeakerLabel: "我",
      displayName: "我",
      body: "我关注团队的业务复杂度。",
      sourceStart: 13,
      sourceEnd: 25,
      confidence: 0.96,
      uncertaintyReason: null,
      ignored: false,
      version: 1,
    },
  ],
};

describe("CleanupWorkbench", () => {
  afterEach(cleanupDom);

  it("focuses uncertainty, supports role correction, and gates confirmation", () => {
    const onSave = vi.fn();
    const onConfirm = vi.fn();
    render(
      <CleanupWorkbench
        cleanup={cleanup}
        busy={false}
        onSave={onSave}
        onConfirm={onConfirm}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByText("1 段需要确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("第 1 段说话人"), {
      target: { value: "interviewer" },
    });
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ speakerRole: "interviewer" }),
      ]),
      3,
    );
  });

  it("can swap candidate and interviewer labels without hiding segments", () => {
    const onSave = vi.fn();
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          segments: cleanup.segments.map((segment, index) => ({
            ...segment,
            speakerRole: index === 0 ? "interviewer" : "candidate",
          })),
        }}
        busy={false}
        onSave={onSave}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "对调双方身份" }));
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onSave).toHaveBeenCalledWith(
      [
        expect.objectContaining({ speakerRole: "candidate" }),
        expect.objectContaining({ speakerRole: "interviewer" }),
      ],
      3,
    );
    expect(screen.getAllByText("你为什么选择我们公司？")[0]).toBeVisible();
    expect(screen.getAllByText("我关注团队的业务复杂度。")[0]).toBeVisible();
  });

  it("allows an uncertain segment to be excluded before confirmation", () => {
    const onSave = vi.fn();
    render(
      <CleanupWorkbench
        cleanup={cleanup}
        busy={false}
        onSave={onSave}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "忽略这段，不进入后续分析" }));
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ ignored: true })]),
      3,
    );
  });

  it("shows persisted running controls and retries a failed cleanup", () => {
    const onStop = vi.fn();
    const onResume = vi.fn();
    const { rerender } = render(
      <CleanupWorkbench
        cleanup={{ ...cleanup, status: "running", stage: "cleanup" }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={onStop}
        onResume={onResume}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("刷新或离开不会丢失已完成结果");
    fireEvent.click(screen.getByRole("button", { name: "停止整理" }));
    expect(onStop).toHaveBeenCalledOnce();

    rerender(
      <CleanupWorkbench
        cleanup={{ ...cleanup, status: "failed", stage: "cleanup" }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={onStop}
        onResume={onResume}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "重试未完成部分" }));
    expect(onResume).toHaveBeenCalledOnce();
  });
});
