import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurationConversation } from "./CurationConversation";
import type { CurationSession, QuestionCandidate } from "./reviewTypes";

const items = Array.from({ length: 5 }, (_, index) => ({ ordinal: index + 1, candidateId: `c${index + 1}`, title: `题目 ${index + 1}`, topics: ["backend"], difficulty: "medium" as const, sourceCount: 1, recommendation: "recommend_confirm" }));
const session = { id: "s1", title: "整理", stage: "waiting_for_command", summary: { items }, summaryVersion: 2, messages: [{ id: "m1", executionId: "e1", role: "assistant", content: "整理完成", messageKind: "curation_summary", payload: {}, createdAt: "2026-07-15T10:00:00Z" }], executionStartedAt: null, executionFinishedAt: null } as CurationSession;
const candidate = (id: string): QuestionCandidate => ({ id, batchId: "b1", curationSessionId: "s1", sourceRefs: [], correctionNote: "建议核对答案", reviewNote: "", reviewNoteUpdatedAt: null, duplicateOfQuestionId: null, duplicateQuestion: null, status: "review_pending", createdAt: "now", updatedAt: "now", question: { questionId: `q-${id}`, documentId: `d-${id}`, contentHash: "hash", title: `题目 ${id.slice(1)}`, questionText: "问题", referenceAnswer: "答案", topics: ["backend"], difficulty: "medium", keyPoints: ["关键点"], followUps: [] }, draft: { id: `d-${id}`, title: `题目 ${id.slice(1)}`, markdown: `# 题目 ${id.slice(1)}`, status: "review_pending", version: 1, contentHash: "hash", documentType: "question" } });

describe("CurationConversation artifacts", () => {
  afterEach(cleanup);
  it("shows three files by default, expands within the artifact list, and exposes file actions", () => {
    const onOpen = vi.fn(); const onPublish = vi.fn(); const onSaveNote = vi.fn();
    render(<CurationConversation session={session} candidates={Object.fromEntries(items.map((item) => [item.candidateId, candidate(item.candidateId)]))} optimisticMessage={null} busy={false} onSubmit={vi.fn()} onOpenCandidate={onOpen} onPublishCandidate={onPublish} onSaveNote={onSaveNote} />);
    const files = screen.getByRole("region", { name: "已生成文件" });
    expect(within(files).getAllByRole("article")).toHaveLength(3);
    fireEvent.click(within(files).getByRole("button", { name: /展开其余 2 个文件/ }));
    expect(within(files).getAllByRole("article")).toHaveLength(5);
    fireEvent.click(within(files).getAllByRole("button", { name: "查看" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "发布" })[0]);
    fireEvent.click(within(files).getAllByRole("button", { name: "备注" })[0]);
    fireEvent.change(screen.getByLabelText("修改备注"), { target: { value: "补充失败恢复" } });
    fireEvent.click(screen.getByRole("button", { name: "保存备注" }));
    expect(onOpen).toHaveBeenCalledWith("c1");
    expect(onPublish).toHaveBeenCalledWith("c1");
    expect(onSaveNote).toHaveBeenCalledWith("c1", "补充失败恢复");
    expect(screen.getByLabelText("回复题匠")).toHaveAttribute("placeholder", expect.stringContaining("输入要求"));
  });

  it("sends with Enter and keeps Shift+Enter for a newline", () => {
    const onSubmit = vi.fn();
    render(<CurationConversation session={session} optimisticMessage={null} busy={false} onSubmit={onSubmit} />);
    const input = screen.getByLabelText("回复题匠");
    expect(input).toHaveAttribute("rows", "1");
    fireEvent.change(input, { target: { value: "发布这题" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("发布这题");
  });

  it("keeps execution settings compact without hiding their controls", () => {
    const onModelChange = vi.fn();
    const onReasoningEffortChange = vi.fn();
    render(
      <CurationConversation
        session={session}
        optimisticMessage={null}
        busy={false}
        models={[{ id: "model-1", label: "火山 / glm" }]}
        selectedModelId="model-1"
        reasoningEffort="medium"
        onModelChange={onModelChange}
        onReasoningEffortChange={onReasoningEffortChange}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText("火山 / glm · 中等")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("本次执行模型"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("思考强度"), { target: { value: "high" } });
    expect(onModelChange).toHaveBeenCalledWith("");
    expect(onReasoningEffortChange).toHaveBeenCalledWith("high");
  });

  it("shows execution-scoped streaming output and swaps send for stop", () => {
    const onStop = vi.fn();
    render(
      <CurationConversation
        session={session}
        optimisticMessage={null}
        busy
        activeExecutionId="run-1"
        streamingState={{ text: "正在给出建议", status: "running" }}
        models={[{ id: "model-1", label: "Model 1" }]}
        selectedModelId="model-1"
        reasoningEffort="medium"
        onModelChange={vi.fn()}
        onReasoningEffortChange={vi.fn()}
        onStop={onStop}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("正在给出建议")).toBeInTheDocument();
    expect(screen.getByText("Agent 处理中")).toBeInTheDocument();
    expect(screen.getByLabelText("本次执行模型")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("offers one-click publication from the generated files header", () => {
    const onBulkPublish = vi.fn();
    render(
      <CurationConversation
        session={session}
        optimisticMessage={null}
        busy={false}
        onSubmit={vi.fn()}
        onBulkPublish={onBulkPublish}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "一键发布" }));
    expect(onBulkPublish).toHaveBeenCalledTimes(1);
  });
});
