import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveCreateFlow } from "./RetrospectiveCreateFlow";

const targets = [
  {
    id: "target-1",
    workspaceId: "w1",
    companyName: "星河科技",
    roleName: "后端工程师",
    seniority: "3-5 年",
    sourceUrl: null,
    lifecycleStatus: "active" as const,
    currentDocumentVersionId: null,
    version: 1,
    createdAt: "2026-08-01 00:00:00",
    updatedAt: "2026-08-01 00:00:00",
  },
];

describe("RetrospectiveCreateFlow", () => {
  afterEach(cleanup);

  it("requires a target, exposes the two input meanings, and submits pasted text", () => {
    const onSubmit = vi.fn();
    render(
      <RetrospectiveCreateFlow
        targets={targets}
        busy={false}
        onCancel={vi.fn()}
        onCreateTarget={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "开始整理" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请选择求职目标");

    fireEvent.change(screen.getByLabelText("求职目标"), {
      target: { value: "target-1" },
    });
    fireEvent.change(screen.getByLabelText("复盘名称"), {
      target: { value: "星河科技后端一面" },
    });
    fireEvent.change(screen.getByLabelText("面试轮次"), {
      target: { value: "一面" },
    });
    fireEvent.click(screen.getByRole("radio", { name: /事后回忆/ }));
    fireEvent.change(screen.getByLabelText("面试文字"), {
      target: { value: "面试官：请介绍一下缓存治理。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始整理" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        targetId: "target-1",
        sourceKind: "recollection",
        body: "面试官：请介绍一下缓存治理。",
      }),
    );
  });

  it("accepts txt and markdown files but rejects unrelated formats", async () => {
    render(
      <RetrospectiveCreateFlow
        targets={targets}
        initialTargetId="target-1"
        busy={false}
        onCancel={vi.fn()}
        onCreateTarget={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("导入文字文件"), {
      target: { files: [new File(["content"], "interview.pdf")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("仅支持 TXT 或 Markdown");

    fireEvent.change(screen.getByLabelText("导入文字文件"), {
      target: { files: [new File(["面试记录"], "interview.md", { type: "text/markdown" })] },
    });
    expect(await screen.findByDisplayValue("面试记录")).toBeInTheDocument();
    expect(screen.getByText("4 / 500,000 字符")).toBeInTheDocument();
  });

  it("creates a lightweight target inline and selects it for the retrospective", async () => {
    const onCreateTarget = vi.fn().mockResolvedValue(targets[0]);
    render(
      <RetrospectiveCreateFlow
        targets={targets}
        busy={false}
        onCancel={vi.fn()}
        onCreateTarget={onCreateTarget}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "快速新建求职目标" }));
    fireEvent.change(screen.getByLabelText("公司"), { target: { value: "星河科技" } });
    fireEvent.change(screen.getByLabelText("岗位"), { target: { value: "后端工程师" } });
    fireEvent.change(screen.getByLabelText("经验或职级"), { target: { value: "3-5 年" } });
    fireEvent.click(screen.getByRole("button", { name: "保存目标" }));

    await waitFor(() => expect(onCreateTarget).toHaveBeenCalledWith({
      companyName: "星河科技",
      roleName: "后端工程师",
      seniority: "3-5 年",
    }));
    expect(screen.getByLabelText("求职目标")).toHaveValue("target-1");
  });
});
