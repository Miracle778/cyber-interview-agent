import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { WorkspaceConfig } from "./settingsApi";
import { SettingsPage } from "./SettingsPage";

function renderSettings(workspace: WorkspaceConfig | null, onWorkspaceReady = vi.fn()) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SettingsPage workspace={workspace} onWorkspaceReady={onWorkspaceReady} />
    </QueryClientProvider>,
  );
}

const workspaceResource = {
  id: "w1",
  displayName: "测试工作区",
  rootPath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
  available: true,
  lifecycleStatus: "active",
  isCurrent: true,
  recycledAt: null,
  activeExecutionCount: 0,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-10T00:00:00Z",
};

function installSettingsFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    const method = init?.method ?? "GET";
    if ((url === "/api/settings/workspaces" || url === "/api/settings/workspaces?status=all") && method === "GET") {
      return Response.json([workspaceResource]);
    }
    if (url === "/api/settings/workspaces" && method === "POST") {
      return Response.json(workspaceResource, { status: 201 });
    }
    if (url === "/api/settings/providers") {
      return Response.json([]);
    }
    if (url.endsWith("/model-bindings")) {
      return Response.json({ workspaceId: "w1", bindings: {} });
    }
    if (url === "/api/agent/sessions?workspaceId=w1") {
      return Response.json([]);
    }
    if (url === "/api/agent/actions?workspaceId=w1&status=pending") {
      return Response.json([]);
    }
    if (url === "/api/settings/agent-diagnostics") {
      return Response.json({
        advancedEnabled: false,
        updatedAt: "2026-07-30 00:00:00",
      });
    }
    return Response.json({ code: "unexpected", message: url }, { status: 500 });
  });
}

describe("SettingsPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("restores a registered workspace and shows provider and binding management", async () => {
    installSettingsFetch();
    const workspace: WorkspaceConfig = {
      workspacePath: workspaceResource.rootPath,
      id: workspaceResource.id,
      vaultPath: workspaceResource.vaultPath,
    };

    renderSettings(workspace);

    expect(await screen.findByRole("heading", { name: "配置概览" })).toBeInTheDocument();
    expect(screen.queryByText("模型服务和密钥由所有工作区复用")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent Runtime")).not.toBeInTheDocument();
    expect(screen.getByText(workspace.workspacePath)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "模型服务" }));
    expect(await screen.findByRole("heading", { name: "模型服务" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "任务使用的模型" })).toBeInTheDocument();
    expect(screen.queryByText("Agent Runtime")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "运行诊断" }));
    expect(
      await screen.findByRole("switch", { name: "高级诊断模式" }),
    ).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Agent Runtime")).toBeInTheDocument();
  });

  it("initializes workspace and reports it to AppShell", async () => {
    installSettingsFetch();
    const onWorkspaceReady = vi.fn();

    renderSettings(null, onWorkspaceReady);

    fireEvent.click(screen.getByRole("button", { name: "下一步：创建工作区" }));
    fireEvent.change(screen.getByLabelText("本地文件夹路径"), {
      target: { value: workspaceResource.rootPath },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建工作区" }));

    await waitFor(() =>
      expect(onWorkspaceReady).toHaveBeenCalledWith({
        workspacePath: workspaceResource.rootPath,
        id: workspaceResource.id,
        displayName: workspaceResource.displayName,
        vaultPath: workspaceResource.vaultPath,
      }),
    );
    expect(await screen.findByText(workspaceResource.displayName)).toBeInTheDocument();
  });

  it("shows actionable advice when workspace path is empty", () => {
    renderSettings(null);

    fireEvent.click(screen.getByRole("button", { name: "下一步：创建工作区" }));
    fireEvent.click(screen.getByRole("button", { name: "创建工作区" }));

    expect(screen.getByText("错误：请输入本地文件夹路径")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "运行自检" })).not.toBeInTheDocument();
  });
});
