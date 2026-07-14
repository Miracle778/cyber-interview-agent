import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it.each([
    ["/review", "复习"],
    ["/knowledge", "知识库"],
    ["/settings", "设置"],
  ])("renders %s as an independent page", async (path, heading) => {
    window.history.replaceState({}, "", path);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    const otherHeadings = ["复习", "知识库", "设置"].filter((item) => item !== heading);
    otherHeadings.forEach((item) => {
      expect(screen.queryByRole("heading", { level: 1, name: item })).not.toBeInTheDocument();
    });
  });

  it.each(["/", "/unknown"])("redirects %s to review", async (path) => {
    window.history.replaceState({}, "", path);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "复习" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/review");
  });

  it("exposes only implemented destinations and marks the current page", async () => {
    window.history.replaceState({}, "", "/knowledge");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    const navigation = await screen.findByRole("navigation", { name: "主导航" });
    expect(navigation).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "知识库" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "复习" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "设置" })).toBeInTheDocument();
    expect(screen.queryByText("模拟面试")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "跳到主内容" })).toHaveAttribute("href", "#main-content");
  });

  it("closes the mobile navigation with Escape and restores focus", async () => {
    window.history.replaceState({}, "", "/review");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    const trigger = await screen.findByRole("button", { name: "打开导航" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "主导航" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("shows the R2 review setup for a ready workspace", async () => {
    window.history.replaceState({}, "", "/review");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/health")) return Response.json({ status: "ok" });
      if (url.endsWith("/api/settings/workspace")) return Response.json({ id: "w1", workspacePath: "/tmp/cyber-demo", vaultPath: "/tmp/cyber-demo/knowledge-vault" });
      if (url.includes("/api/review/rounds?") || url.includes("/api/review/questions?") || url.endsWith("/api/settings/providers")) return Response.json([]);
      if (url.includes("/model-bindings")) return Response.json({ workspaceId: "w1", bindings: {} });
      throw new Error(`unexpected ${url}`);
    });

    render(<App />);

    expect(await screen.findByText("围绕题库持续练习，形成可追踪的掌握度。")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "创建复习轮次" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /题库整理/ })).toBeInTheDocument();
    expect(screen.getByText("当前筛选题量不足，请减少题量或先去“题库整理”确认更多题目。")).toBeInTheDocument();
  });

  it("guides knowledge users without a workspace to settings", async () => {
    window.history.replaceState({}, "", "/knowledge");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    expect(await screen.findByText("管理 Agent 可引用的资料、草稿与 Vault 索引。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往设置" })).toHaveAttribute("href", "/settings");
    expect(screen.queryByLabelText("流程状态")).not.toBeInTheDocument();
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
            id: "w1",
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

  it("shows the workspace initialization empty state after backend connects", async () => {
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

    expect(await screen.findByText("后端已连接")).toBeInTheDocument();
    expect(screen.getByText("Workspace：待初始化")).toBeInTheDocument();
    expect(screen.getByText("请先初始化工作区")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往设置" })).toHaveAttribute("href", "/settings");
  });
});
