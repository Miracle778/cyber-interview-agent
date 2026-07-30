import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentDiagnosticsSettings } from "./AgentDiagnosticsSettings";

function renderSettings() {
  return render(
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })}
    >
      <AgentDiagnosticsSettings />
    </QueryClientProvider>,
  );
}

describe("AgentDiagnosticsSettings", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("defaults off and requires a private-content disclosure before enabling", async () => {
    const requests: Array<{ method: string; body?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const method = init?.method ?? "GET";
      requests.push({ method, body: init?.body as string | undefined });
      if (method === "PUT") {
        return Response.json({
          advancedEnabled: true,
          updatedAt: "2026-07-30 00:00:00",
        });
      }
      return Response.json({
        advancedEnabled: false,
        updatedAt: "2026-07-29 00:00:00",
      });
    });

    renderSettings();

    const toggle = await screen.findByRole("switch", { name: "高级诊断模式" });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);

    expect(
      screen.getByRole("dialog", { name: "开启高级诊断模式" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/简历、JD、回答、Prompt、Tool 参数/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/管理员|账号权限|诊断权限/);
    expect(requests.filter((item) => item.method === "PUT")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "确认并开启" }));

    await waitFor(() =>
      expect(toggle).toHaveAttribute("aria-checked", "true"),
    );
    expect(requests.at(-1)?.body).toBe('{"advancedEnabled":true}');
  });

  it("restores an enabled setting and disables it immediately", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const method = init?.method ?? "GET";
      requests.push(method);
      return Response.json({
        advancedEnabled: method === "GET",
        updatedAt: "2026-07-30 00:00:00",
      });
    });

    renderSettings();

    const toggle = await screen.findByRole("switch", { name: "高级诊断模式" });
    await waitFor(() =>
      expect(toggle).toHaveAttribute("aria-checked", "true"),
    );
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(toggle).toHaveAttribute("aria-checked", "false"),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requests).toEqual(["GET", "PUT"]);
  });

  it("keeps the previous value and shows an actionable save failure", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if ((init?.method ?? "GET") === "PUT") {
        return Response.json(
          { code: "settings_write_failed", message: "保存失败" },
          { status: 500 },
        );
      }
      return Response.json({
        advancedEnabled: false,
        updatedAt: "2026-07-29 00:00:00",
      });
    });

    renderSettings();

    const toggle = await screen.findByRole("switch", {
      name: "高级诊断模式",
    });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "确认并开启" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
    expect(
      screen.getByRole("switch", { name: "高级诊断模式" }),
    ).toHaveAttribute("aria-checked", "false");
  });
});
