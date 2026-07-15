import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewLanding } from "./ReviewLanding";

describe("ReviewLanding", () => {
  afterEach(cleanup);

  it("blocks creation and routes to curation when no questions are ready", () => {
    const create = vi.fn();
    const catalog = vi.fn();
    render(<ReviewLanding rounds={[]} questionCount={0} onCreate={create} onOpen={vi.fn()} onCatalog={catalog} />);
    expect(screen.getByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建复习" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "题库尚未准备好" })).toHaveTextContent("当前没有已确认题目");
    fireEvent.click(screen.getByRole("button", { name: "去题库整理" }));
    expect(catalog).toHaveBeenCalledOnce();
    expect(create).not.toHaveBeenCalled();
  });

  it("allows a small round while suggesting more curation", () => {
    const create = vi.fn();
    render(<ReviewLanding rounds={[]} questionCount={4} onCreate={create} onOpen={vi.fn()} onCatalog={vi.fn()} />);
    expect(screen.getByRole("status", { name: "题库题量偏少" })).toHaveTextContent("当前题库有 4 道题");
    fireEvent.click(screen.getByRole("button", { name: "创建复习" }));
    expect(create).toHaveBeenCalledOnce();
  });

  it("keeps the normal history view quiet when the catalog is ready", () => {
    render(<ReviewLanding rounds={[]} questionCount={10} onCreate={vi.fn()} onOpen={vi.fn()} onCatalog={vi.fn()} />);
    expect(screen.queryByRole("status", { name: "题库尚未准备好" })).toBeNull();
    expect(screen.queryByRole("status", { name: "题库题量偏少" })).toBeNull();
  });
});
