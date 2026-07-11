import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ReviewPage } from "./ReviewPage";
import type { ReviewQuestion } from "./reviewTypes";

const workspace: WorkspaceConfig = {
  id: "w1",
  workspacePath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
};

const question: ReviewQuestion = {
  id: "q1",
  title: "缓存穿透",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "缓存穿透是请求不存在的数据导致缓存无法命中。",
  topics: ["缓存"],
  difficulty: "medium",
  keyPoints: ["缓存空值", "布隆过滤器"],
  followUps: [],
  mastery: "unknown",
};

describe("ReviewPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("requires a draft question before review", () => {
    render(
      <MemoryRouter>
        <ReviewPage
          workspace={workspace}
          draftQuestion={null}
          latestReportMarkdown=""
          onReportMarkdownChange={vi.fn()}
          onReportConfirmed={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("请先上传资料生成题库草稿")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送回答" })).toBeDisabled();
  });

  it("runs review and displays evaluation report", async () => {
    const onReportMarkdownChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          current_question: question,
          evaluation: {
            score: "partial",
            missing_key_points: ["布隆过滤器"],
            evidence: "可以缓存空值。",
          },
          report_markdown: "# 单轮复习报告\n\n得分：72",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={question}
        latestReportMarkdown=""
        onReportMarkdownChange={onReportMarkdownChange}
        onReportConfirmed={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("你的回答"), { target: { value: "可以缓存空值。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送回答" }));

    expect(await screen.findByText("评分：partial")).toBeInTheDocument();
    expect(screen.getByText("缺失点：布隆过滤器")).toBeInTheDocument();
    expect(screen.getByText("证据：可以缓存空值。")).toBeInTheDocument();
    await waitFor(() => expect(onReportMarkdownChange).toHaveBeenCalledWith("# 单轮复习报告\n\n得分：72"));
  });

  it("confirms report and displays written paths", async () => {
    const onReportConfirmed = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          reportPath: "/tmp/cyber-demo/knowledge-vault/20_review_sessions/session.md",
          masteryPath: "/tmp/cyber-demo/knowledge-vault/30_mastery/global_mastery_review_pending.md",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={question}
        latestReportMarkdown="# 单轮复习报告"
        onReportMarkdownChange={vi.fn()}
        onReportConfirmed={onReportConfirmed}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "确认报告" }));

    expect(await screen.findByText("报告：/tmp/cyber-demo/knowledge-vault/20_review_sessions/session.md")).toBeInTheDocument();
    expect(screen.getByText("掌握度：/tmp/cyber-demo/knowledge-vault/30_mastery/global_mastery_review_pending.md")).toBeInTheDocument();
    await waitFor(() => expect(onReportConfirmed).toHaveBeenCalled());
  });

  it("shows actionable advice when answer is empty", () => {
    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={question}
        latestReportMarkdown=""
        onReportMarkdownChange={vi.fn()}
        onReportConfirmed={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "发送回答" }));

    expect(screen.getByText("错误：请输入你的回答")).toBeInTheDocument();
    expect(screen.getByText("下一步：根据当前题目输入一段回答")).toBeInTheDocument();
  });
});
