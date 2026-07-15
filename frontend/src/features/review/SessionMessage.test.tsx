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
  createdAt: "2026-07-15T10:02:03Z",
};

describe("SessionMessage", () => {
  afterEach(cleanup);

  it("does not infer a source card from free-form message text", () => {
    render(<SessionMessage message={baseMessage} />);

    expect(screen.getByText(/这只是普通的可见回复/)).toBeInTheDocument();
    expect(screen.getByText(/^\d{2}:\d{2}:\d{2}$/)).toHaveAttribute("datetime", "2026-07-15T10:02:03Z");
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

  it("shows elapsed time on a curation result", () => {
    render(<SessionMessage message={{ ...baseMessage, messageKind: "curation_summary" }} startedAt="2026-07-15T10:00:00Z" />);

    const timing = screen.getByText("· 耗时 2 分 3 秒").parentElement;
    expect(timing).toHaveTextContent(/\d{2}:\d{2}:\d{2}· 耗时 2 分 3 秒/);
  });

  it("uses Beijing time and command-local elapsed time for a command receipt", () => {
    render(
      <SessionMessage
        message={{
          ...baseMessage,
          messageKind: "command_receipt",
          createdAt: "2026-07-15 14:39:06",
          payload: { startedAt: "2026-07-15T14:39:00+00:00" },
        }}
        startedAt="2026-07-15T14:39:00+00:00"
      />,
    );

    expect(screen.getByText("22:39:06")).toBeInTheDocument();
    expect(screen.getByText("· 耗时 6 秒")).toBeInTheDocument();
  });
});
