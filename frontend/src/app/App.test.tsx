import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the MVP shell in workflow order", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(null), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getByText("复习闭环 MVP")).toBeInTheDocument();

    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .slice(0, 3)
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["设置", "知识文档", "复习"]);
  });

  it("shows backend connected and restores workspace", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workspacePath: "/tmp/cyber-demo",
            vaultPath: "/tmp/cyber-demo/knowledge-vault",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );

    render(<App />);

    expect(await screen.findByText("后端已连接")).toBeInTheDocument();
    expect(await screen.findByText("Workspace：/tmp/cyber-demo")).toBeInTheDocument();
  });

  it("shows backend disconnected advice when health fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

    render(<App />);

    expect(await screen.findByText("后端未连接，请确认 FastAPI 服务已启动")).toBeInTheDocument();
  });

  it("shows initial workflow status panel after backend connects", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(null), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    render(<App />);

    expect(await screen.findByText("后端连接：已连接")).toBeInTheDocument();
    expect(screen.getByText("Workspace：待初始化")).toBeInTheDocument();
    expect(screen.getByText("题库草稿：待生成")).toBeInTheDocument();
    expect(screen.getByText("复习报告：待生成")).toBeInTheDocument();
    expect(screen.getByText("Vault 索引：待扫描")).toBeInTheDocument();
    expect(screen.getByText("下一步：初始化工作区")).toBeInTheDocument();
  });
});
