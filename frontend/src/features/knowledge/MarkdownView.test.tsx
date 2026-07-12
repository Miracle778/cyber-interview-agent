import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarkdownErrorBoundary, MarkdownView } from "./MarkdownView";

describe("MarkdownView", () => {
  afterEach(cleanup);

  it("renders Markdown semantics without executing raw HTML", () => {
    render(
      <MarkdownView
        markdown={[
          "# 缓存穿透",
          "",
          "- 缓存空值",
          "- 布隆过滤器",
          "",
          "<script>alert('unsafe')</script>",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { name: "缓存穿透" })).toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText("<script>alert('unsafe')</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("opens external links safely and keeps internal links in the app", () => {
    render(
      <MarkdownView markdown="[外部](https://example.com) [内部](/knowledge)" />,
    );

    expect(screen.getByRole("link", { name: "外部" })).toMatchObject({
      target: "_blank",
      rel: "noreferrer noopener",
    });
    expect(screen.getByRole("link", { name: "内部" })).not.toHaveAttribute("target");
  });

  it("falls back to safe plain text when rendering fails", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenMarkdown(): never {
      throw new Error("renderer failed");
    }

    render(
      <MarkdownErrorBoundary markdown="# 安全降级">
        <BrokenMarkdown />
      </MarkdownErrorBoundary>,
    );

    expect(screen.getByText("# 安全降级")).toHaveClass("markdown-view--fallback");
  });
});
