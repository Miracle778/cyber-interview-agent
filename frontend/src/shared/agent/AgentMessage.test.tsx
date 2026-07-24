import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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
});
