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
  completedItems: 1,
  totalItems: 1,
  activeItems: 0,
  failedItems: 0,
  currentWorkKey: null,
  lastErrorCode: null,
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
  afterEach(() => {
    cleanupDom();
    vi.clearAllMocks();
  });

  it("reviews one continuous transcript and only lists sparse uncertain issues", () => {
    const onSaveDocument = vi.fn();
    const transcript = "面试官：介绍一下项目。\n\n候选人：我参与了数字签名服务。";
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          documentBody: transcript,
          documentSha256: "digest",
          segments: [],
          corrections: [],
          reviewIssues: [{
            id: "issue-1",
            ordinal: 1,
            documentStart: transcript.indexOf("参与"),
            documentEnd: transcript.indexOf("参与") + 2,
            excerpt: "参与",
            suggestion: "负责",
            issueKind: "semantic",
            reason: "职责级别可能改变原意",
            confidence: 0.55,
            decision: "pending",
          }],
        }}
        busy={false}
        onSave={vi.fn()}
        onSaveDocument={onSaveDocument}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("整理后的完整文字")).toHaveValue(transcript);
    expect(screen.getByText("还有 1 处需要确认")).toBeInTheDocument();
    expect(screen.getByText("第 1 / 1 项")).toBeInTheDocument();
    expect(screen.getByText("全部问题")).toBeInTheDocument();
    expect(screen.getByLabelText("待确认问题列表，共 1 项")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /参与.*语义待确认/ })).toBeInTheDocument();
    expect(screen.getByLabelText("建议修改")).toHaveTextContent("参与");
    expect(screen.getByLabelText("建议修改")).toHaveTextContent("负责");
    expect(screen.getByRole("button", { name: "采用这处修改" })).toBeVisible();
    expect(screen.getByText("职责级别可能改变原意")).toBeVisible();
    expect(screen.queryByText("第 1 段")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保留当前文字" }));
    fireEvent.click(screen.getByRole("button", { name: "保存整理稿" }));
    expect(onSaveDocument).toHaveBeenCalledWith(
      transcript,
      3,
      [{ id: "issue-1", decision: "kept" }],
    );
  });

  it("shows an ambiguous legacy candidate as a non-actionable review hint", () => {
    const transcript = "候选人：数字签名用于发布，数字签名用于部署。";
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          documentBody: transcript,
          documentSha256: "digest",
          segments: [],
          corrections: [],
          reviewIssues: [{
            id: "issue-ambiguous",
            ordinal: 1,
            documentStart: 0,
            documentEnd: transcript.length,
            excerpt: transcript,
            suggestion: "代码签名",
            issueKind: "semantic",
            reason: "模型返回的不确定项无法在当前目标正文中唯一定位，请核对该窗口",
            confidence: 0.6,
            decision: "pending",
          }],
        }}
        busy={false}
        onSave={vi.fn()}
        onSaveDocument={vi.fn()}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByText("需要核对的上下文")).toBeVisible();
    expect(screen.getByText("模型标记的候选词")).toBeVisible();
    expect(screen.getByText("代码签名")).toBeVisible();
    expect(screen.getByText("没有找到唯一对应的原词，不能自动替换")).toBeVisible();
    expect(screen.queryByRole("button", { name: "采用这处修改" })).not.toBeInTheDocument();
  });

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

    expect(screen.getByText("还需处理 1 项")).toBeInTheDocument();
    expect(screen.getByText("说话人待确认 1")).toBeInTheDocument();
    expect(screen.getByText("模型整理稿")).toBeInTheDocument();
    expect(screen.getByText("这里直接展示模型返回的 correctedText；可能改变原意的内容仍需在下方确认。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("第 1 段说话人"), {
      target: { value: "interviewer" },
    });
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));
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

    fireEvent.click(screen.getByText("批量操作"));
    fireEvent.click(screen.getByRole("button", { name: "对调双方身份" }));
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));
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
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));
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
        cleanup={{ ...cleanup, status: "running", stage: "cleanup", totalItems: 4, activeItems: 2 }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={onStop}
        onResume={onResume}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("已保存 1 / 4 个文本窗口");
    expect(screen.getByRole("status")).toHaveTextContent("正在并行处理 2 个文本窗口");
    fireEvent.click(screen.getByRole("button", { name: "停止整理" }));
    expect(onStop).toHaveBeenCalledOnce();

    rerender(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          status: "failed",
          stage: "cleanup",
          completedItems: 1,
          totalItems: 2,
          activeItems: 0,
          failedItems: 1,
          currentWorkKey: "window:6000:12000",
          lastErrorCode: "provider_timeout",
        }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={onStop}
        onResume={onResume}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("模型响应超时");
    expect(screen.getByText("已保存 1 / 2 个文本窗口，1 个窗口待重试")).toBeVisible();
    expect(screen.getAllByText("你为什么选择我们公司？")[0]).toBeVisible();
    expect(screen.getByRole("button", { name: "保存并稍后继续" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重试未完成部分" }));
    expect(onResume).toHaveBeenCalledOnce();
  });

  it("blocks confirmation until every high-risk transcript correction is resolved", () => {
    const onSave = vi.fn();
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          segments: cleanup.segments.map((segment) => ({
            ...segment,
            speakerRole: segment.id === "segment-1" ? "interviewer" : "candidate",
          })),
          corrections: [
            {
              id: "correction-1",
              segmentId: "segment-2",
              sourceStart: 15,
              sourceEnd: 18,
              originalText: "瑞迪斯",
              suggestedText: "Redis",
              adoptedText: "瑞迪斯",
              changeType: "semantic",
              riskLevel: "high",
              reason: "技术结论可能发生变化",
              confidence: 0.62,
              decision: "pending",
            },
          ],
        }}
        busy={false}
        onSave={onSave}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByText("还需处理 1 项")).toBeVisible();
    expect(screen.getByText("关键文字待确认 1")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "采用修改" }));
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.any(Array),
      3,
      [{ id: "correction-1", decision: "accepted", manualText: null }],
    );
  });

  it("keeps every pending correction as original in one saved action", () => {
    const onSave = vi.fn();
    const pendingCorrections = Array.from({ length: 3 }, (_, index) => ({
      id: `correction-${index + 1}`,
      segmentId: "segment-2",
      sourceStart: 15 + index,
      sourceEnd: 16 + index,
      originalText: `原${index + 1}`,
      suggestedText: `建议${index + 1}`,
      adoptedText: `原${index + 1}`,
      changeType: "semantic" as const,
      riskLevel: "high" as const,
      reason: "无法唯一确认",
      confidence: 0.62,
      decision: "pending" as const,
    }));
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          segments: cleanup.segments.map((segment) => ({
            ...segment,
            speakerRole: segment.id === "segment-1" ? "interviewer" : "candidate",
          })),
          corrections: pendingCorrections,
        }}
        busy={false}
        onSave={onSave}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("批量操作"));
    fireEvent.click(screen.getByRole("button", { name: "全部保留原文并保存（3）" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.any(Array),
      3,
      pendingCorrections.map((item) => ({
        id: item.id,
        decision: "kept_original",
        manualText: null,
      })),
    );
  });

  it("shows one blocking correction at a time and folds automatic cleanup", () => {
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          segments: cleanup.segments.map((segment) => ({
            ...segment,
            speakerRole: segment.id === "segment-1" ? "interviewer" : "candidate",
          })),
          corrections: [
            {
              id: "auto-1",
              segmentId: "segment-2",
              sourceStart: 13,
              sourceEnd: 14,
              originalText: "，",
              suggestedText: "。",
              adoptedText: "。",
              changeType: "formatting",
              riskLevel: "low",
              reason: "补充断句",
              confidence: 0.98,
              decision: "auto_accepted",
            },
            {
              id: "pending-1",
              segmentId: "segment-2",
              sourceStart: 15,
              sourceEnd: 18,
              originalText: "十倍",
              suggestedText: "十倍以上",
              adoptedText: "十倍",
              changeType: "semantic",
              riskLevel: "high",
              reason: "数量范围发生变化",
              confidence: 0.45,
              decision: "pending",
            },
            {
              id: "pending-2",
              segmentId: "segment-2",
              sourceStart: 19,
              sourceEnd: 22,
              originalText: "没有",
              suggestedText: "有",
              adoptedText: "没有",
              changeType: "semantic",
              riskLevel: "high",
              reason: "否定关系发生变化",
              confidence: 0.51,
              decision: "pending",
            },
          ],
        }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getAllByText("已自动整理 1 处")).toHaveLength(2);
    expect(screen.getByText("第 1 / 2 个文字问题")).toBeVisible();
    expect(screen.getByText("十倍")).toBeVisible();
    expect(screen.queryByText("没有")).not.toBeInTheDocument();
    expect(screen.queryByText("45%")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "采用修改" }));

    expect(screen.getByText("第 2 / 2 个文字问题")).toBeVisible();
    expect(screen.getByText("没有")).toBeVisible();
    expect(screen.queryByText("十倍")).not.toBeInTheDocument();
  });

  it("keeps manual correction explicit until the user saves its text", () => {
    const onSave = vi.fn();
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          segments: cleanup.segments.map((segment) => ({ ...segment, speakerRole: segment.id === "segment-1" ? "interviewer" : "candidate" })),
          corrections: [{
            id: "pending-manual",
            segmentId: "segment-2",
            sourceStart: 15,
            sourceEnd: 18,
            originalText: "瑞迪斯",
            suggestedText: null,
            adoptedText: "瑞迪斯",
            changeType: "semantic",
            riskLevel: "high",
            reason: "术语无法唯一确认",
            confidence: 0.4,
            decision: "pending",
          }],
        }}
        busy={false}
        onSave={onSave}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "手动修改" }));
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("手工修订文字"), { target: { value: "Redis" } });
    fireEvent.click(screen.getByRole("button", { name: "保存手动修改" }));
    expect(screen.getByRole("button", { name: "确认整理结果" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "保存并稍后继续" }));
    expect(onSave).toHaveBeenCalledWith(expect.any(Array), 3, [{ id: "pending-manual", decision: "manual", manualText: "Redis" }]);
  });

  it("shows persisted elapsed time and determinate progress for long cleanup", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-02T00:02:00Z"));
    render(
      <CleanupWorkbench
        cleanup={{
          ...cleanup,
          status: "running",
          stage: "cleaning",
          completedItems: 1,
          totalItems: 3,
          activeItems: 1,
          currentWorkKey: "window:4000:8000",
          activeSince: "2026-08-02 00:00:30",
          latestProgressAt: "2026-08-02 00:00:40",
        }}
        busy={false}
        onSave={vi.fn()}
        onConfirm={vi.fn()}
        onStop={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("status")).toHaveTextContent("已运行 1 分 30 秒");
    expect(screen.getByRole("status")).toHaveTextContent("大段录音转写可能需要几分钟");
    expect(screen.getByRole("status")).toHaveTextContent("正在处理原文 4,000 - 8,000");
    vi.useRealTimers();
  });
});
