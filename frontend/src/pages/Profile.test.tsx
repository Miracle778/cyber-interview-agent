import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockEventSource } from "../test/setup";
import { Profile } from "./Profile";

function renderProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Profile />
    </QueryClientProvider>,
  );
}

describe("Profile", () => {
  afterEach(() => {
    MockEventSource.reset();
    vi.restoreAllMocks();
  });

  it("creates a run and shows the pending draft after completion", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ run_id: "run-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            run_id: "run-1",
            status: "completed",
            pending_version: {
              id: "v1",
              content: {
                schema_name: "profile",
                schema_version: 1,
                facts: [{ claim: "三年 Python", evidence_ref: null }],
              },
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    renderProfile();
    await userEvent.type(screen.getByLabelText("个人资料文本"), "三年 Python");
    await userEvent.click(screen.getByRole("button", { name: "抽取" }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    act(() => {
      MockEventSource.instances[0].emit("completed", {
        run_id: "run-1",
        sequence: 1,
        event_type: "completed",
        payload: {},
      });
    });

    expect(await screen.findByRole("button", { name: "批准发布" })).toBeInTheDocument();
    expect(screen.getAllByText("三年 Python").length).toBeGreaterThan(1);
  });
});
