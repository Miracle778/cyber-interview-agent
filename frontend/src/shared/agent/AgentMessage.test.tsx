import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentMessage } from "./AgentMessage";

describe("AgentMessage", () => {
  afterEach(cleanup);

  it("treats SQLite timestamps as UTC and renders Beijing time", () => {
    render(
      <AgentMessage
        role="assistant"
        content="画像已更新"
        createdAt="2026-07-25 08:42:00"
      />,
    );

    expect(screen.getByText("16:42")).toBeInTheDocument();
  });

  it("confirms when an assistant message has been copied", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<AgentMessage role="assistant" content="可复制内容" />);

    fireEvent.click(screen.getByRole("button", { name: "复制消息" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("可复制内容"));
    expect(screen.getByRole("status")).toHaveTextContent("已复制");
  });
});
