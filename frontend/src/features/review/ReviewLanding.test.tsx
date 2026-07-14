import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewLanding } from "./ReviewLanding";

describe("ReviewLanding", () => {
  it("keeps creation separate from history", () => {
    const create = vi.fn();
    render(<ReviewLanding rounds={[]} onCreate={create} onOpen={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建复习" }));
    expect(create).toHaveBeenCalledOnce();
  });
});
