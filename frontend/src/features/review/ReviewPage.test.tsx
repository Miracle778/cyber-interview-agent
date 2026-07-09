import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReviewPage } from "./ReviewPage";

describe("ReviewPage", () => {
  it("renders session list chat and setup panel", () => {
    render(<ReviewPage />);
    expect(screen.getByLabelText("复习会话")).toBeInTheDocument();
    expect(screen.getByLabelText("复习对话")).toBeInTheDocument();
    expect(screen.getByLabelText("复习设置")).toBeInTheDocument();
  });
});
