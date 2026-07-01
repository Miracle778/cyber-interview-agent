import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Home } from "./Home";

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Home />
    </QueryClientProvider>,
  );
}

describe("Home", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading before the health request completes", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));

    renderHome();

    expect(screen.getByText("正在连接后端…")).toBeInTheDocument();
  });

  it("shows the backend health result", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
          version: "0.0.0",
          checks: { database: "skipped", providers: "not_configured" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderHome();

    expect(await screen.findByText("后端运行正常")).toBeInTheDocument();
    expect(screen.getByText("版本 0.0.0")).toBeInTheDocument();
  });

  it("shows an accessible error when health request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));

    renderHome();

    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接后端");
  });
});
