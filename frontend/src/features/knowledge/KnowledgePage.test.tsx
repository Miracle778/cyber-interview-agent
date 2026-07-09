import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KnowledgePage } from "./KnowledgePage";

describe("KnowledgePage", () => {
  it("renders upload and rescan actions", () => {
    render(<KnowledgePage />);
    expect(screen.getByRole("heading", { name: "知识文档" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新扫描 Vault" })).toBeInTheDocument();
  });
});
