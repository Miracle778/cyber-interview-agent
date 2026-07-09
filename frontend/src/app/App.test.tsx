import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the MVP shell in workflow order", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getByText("复习闭环 MVP")).toBeInTheDocument();

    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .slice(0, 3)
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["设置", "知识文档", "复习"]);
  });
});
