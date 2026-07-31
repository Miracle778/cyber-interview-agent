import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentQualityEvaluationSettings } from "./AgentQualityEvaluationSettings";

describe("AgentQualityEvaluationSettings", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("requires confirmation and preserves unrelated evaluation settings", async () => {
    const bodies: string[] = [];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const body = init?.body as string | undefined;
      if (body) bodies.push(body);
      return Response.json({
        enabled: true,
        captureRegressionInputs: Boolean(body),
        automaticSamplePercent: 7,
        automaticDailyCap: 12,
        judgeProviderModelId: "judge-model",
        updatedAt: "2026-08-01 00:00:00",
      });
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AgentQualityEvaluationSettings />
      </QueryClientProvider>,
    );

    const toggle = await screen.findByRole("switch", { name: "记录可回归输入" });
    await waitFor(() => expect(toggle).not.toBeDisabled());
    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(JSON.parse(bodies[0]!)).toEqual({
      enabled: true,
      captureRegressionInputs: true,
      automaticSamplePercent: 7,
      automaticDailyCap: 12,
      judgeProviderModelId: "judge-model",
    });
  });
});
