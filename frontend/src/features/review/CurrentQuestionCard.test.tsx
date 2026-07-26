import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurrentQuestionCard } from "./CurrentQuestionCard";

const question = {
  id: "q1",
  documentId: "resume.md",
  title: "发布幂等",
  questionText: "如何保证长任务中的单题发布幂等？",
  topics: ["Agent", "SQLite"],
  difficulty: "medium" as const,
  requiredKeyPointCount: 2,
  coveredKeyPointCount: 0,
  missingDirections: [] as string[],
  hasAnswer: false,
  hintLevel: 0,
};

describe("CurrentQuestionCard", () => {
  afterEach(cleanup);

  it("keeps the frozen prompt visible without leaking key points before answering", () => {
    render(<CurrentQuestionCard question={question} onHint={vi.fn()} onReveal={vi.fn()} onSkip={vi.fn()} />);

    expect(screen.getByRole("region", { name: "当前题目" })).toHaveTextContent(
      "如何保证长任务中的单题发布幂等？",
    );
    expect(screen.getByText("2 个必答方向")).toBeInTheDocument();
    expect(screen.queryByText("事务边界")).toBeNull();
  });

  it("shows cumulative coverage and missing directions after evaluation", () => {
    render(<CurrentQuestionCard question={{ ...question, hasAnswer: true, coveredKeyPointCount: 1, missingDirections: ["补充失败重试的幂等键"] }} onHint={vi.fn()} onReveal={vi.fn()} onSkip={vi.fn()} />);

    expect(screen.getByText("已覆盖 1 / 2")).toBeInTheDocument();
    expect(screen.getByText("补充失败重试的幂等键")).toBeInTheDocument();
  });

  it("offers progressive help, source disclosure, and explicit skip", () => {
    const onHint = vi.fn();
    const onReveal = vi.fn();
    const onSkip = vi.fn();
    render(<CurrentQuestionCard question={question} onHint={onHint} onReveal={onReveal} onSkip={onSkip} />);

    fireEvent.click(screen.getByRole("button", { name: "查看提示" }));
    fireEvent.click(screen.getByRole("button", { name: "查看答案" }));
    fireEvent.click(screen.getByRole("button", { name: "跳过此题" }));
    fireEvent.click(screen.getByRole("button", { name: "查看来源" }));

    expect(onHint).toHaveBeenCalledOnce();
    expect(onReveal).toHaveBeenCalledOnce();
    expect(onSkip).toHaveBeenCalledOnce();
    expect(screen.getByText("resume.md")).toBeInTheDocument();
  });
});
