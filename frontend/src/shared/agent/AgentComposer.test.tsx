import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentComposer } from "./AgentComposer";

function renderComposer(onSend = vi.fn()) {
  render(
    <AgentComposer
      busy={false}
      stopping={false}
      modelId=""
      models={[]}
      reasoningEffort="none"
      placeholder="输入消息"
      onModelChange={vi.fn()}
      onReasoningEffortChange={vi.fn()}
      onSend={onSend}
      onStop={vi.fn()}
    />,
  );
  return { onSend, input: screen.getByPlaceholderText("输入消息") };
}

describe("AgentComposer", () => {
  afterEach(cleanup);

  it("does not send when Enter confirms IME composition", () => {
    const { input, onSend } = renderComposer();
    fireEvent.change(input, { target: { value: "中文" } });

    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", isComposing: true, keyCode: 229 });
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("中文");
  });

  it("sends with ordinary Enter", () => {
    const { input, onSend } = renderComposer();
    fireEvent.change(input, { target: { value: "检查我的项目经历" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(onSend).toHaveBeenCalledWith("检查我的项目经历");
  });
});
