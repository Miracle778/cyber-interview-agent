import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "./settingsApi";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("tests provider connectivity", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "local-provider",
          name: "Local Provider",
          apiFormat: "openai-compatible",
          baseUrl: "https://api.example.com/v1",
          modelIds: ["model-a"],
          activeModelId: "model-a",
          connectivityStatus: "ok",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<SettingsPage workspace={null} onWorkspaceReady={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Provider 名称"), { target: { value: "Local Provider" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://api.example.com/v1" } });
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "model-a" } });
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));

    expect(await screen.findByText("Provider 连接状态：ok")).toBeInTheDocument();
  });

  it("initializes workspace and reports it to AppShell", async () => {
    const onWorkspaceReady = vi.fn();
    const workspace: WorkspaceConfig = {
      workspacePath: "/tmp/cyber-demo",
      vaultPath: "/tmp/cyber-demo/knowledge-vault",
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(workspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<SettingsPage workspace={null} onWorkspaceReady={onWorkspaceReady} />);

    fireEvent.change(screen.getByLabelText("Workspace Path"), { target: { value: "/tmp/cyber-demo" } });
    fireEvent.click(screen.getByRole("button", { name: "初始化工作区" }));

    await waitFor(() => expect(onWorkspaceReady).toHaveBeenCalledWith(workspace));
    expect(await screen.findByText("Vault：/tmp/cyber-demo/knowledge-vault")).toBeInTheDocument();
  });
});
