import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SessionMessage } from "./SessionMessage";
import type { CurationMessage } from "./reviewTypes";

const baseMessage: CurationMessage = {
  id: "m1",
  executionId: "e1",
  role: "assistant",
  content: "资料: redis.md\n这只是普通的可见回复。",
  messageKind: "text",
  payload: {},
  createdAt: "now",
};

describe("SessionMessage", () => {
  afterEach(cleanup);

  it("does not infer a source card from free-form message text", () => {
    render(<SessionMessage message={baseMessage} />);

    expect(screen.getByText(/这只是普通的可见回复/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /redis\.md/ })).toBeNull();
  });

  it("renders an explicit question card from message kind and payload", () => {
    render(
      <SessionMessage
        message={{
          ...baseMessage,
          messageKind: "question_card",
          payload: { title: "MVCC 题目详情" },
          content: "题目正文",
        }}
      />,
    );

    const toggle = screen.getByRole("button", { name: /MVCC 题目详情/ });
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByText("题目正文")).toBeInTheDocument();
  });
});
