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
  rootPath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
  available: true,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-10T00:00:00Z",
};

function installSettingsFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    const method = init?.method ?? "GET";
    if (url === "/api/settings/workspaces" && method === "GET") {
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
      vaultPath: workspaceResource.vaultPath,
    };

    renderSettings(workspace);

    expect(await screen.findByText("Provider 管理")).toBeInTheDocument();
    expect(screen.getByText("模型用途绑定")).toBeInTheDocument();
    expect(screen.getByText("Agent Runtime")).toBeInTheDocument();
    expect(screen.getByText(workspace.workspacePath)).toBeInTheDocument();
  });

  it("initializes workspace and reports it to AppShell", async () => {
    installSettingsFetch();
    const onWorkspaceReady = vi.fn();

    renderSettings(null, onWorkspaceReady);

    fireEvent.change(screen.getByLabelText("Workspace Path"), {
      target: { value: workspaceResource.rootPath },
    });
    fireEvent.click(screen.getByRole("button", { name: "初始化工作区" }));

    await waitFor(() =>
      expect(onWorkspaceReady).toHaveBeenCalledWith({
        workspacePath: workspaceResource.rootPath,
        vaultPath: workspaceResource.vaultPath,
      }),
    );
    expect(await screen.findByText(`Vault：${workspaceResource.vaultPath}`)).toBeInTheDocument();
    expect(screen.getByText("Provider 管理")).toBeInTheDocument();
    expect(screen.getByText("Agent Runtime")).toBeInTheDocument();
  });

  it("shows actionable advice when workspace path is empty", () => {
    renderSettings(null);

    fireEvent.click(screen.getByRole("button", { name: "初始化工作区" }));

    expect(screen.getByText("错误：请输入 Workspace Path")).toBeInTheDocument();
    expect(screen.getByText("下一步：填写本地 workspace 路径")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "运行自检" })).not.toBeInTheDocument();
  });
});
