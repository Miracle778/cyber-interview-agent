import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileActionPlanCard } from "./ProfileActionPlanCard";

vi.mock("./profileApi", () => ({
  getProfileActionPlan: vi.fn(async () => ({ id: "p1", workspaceId: "w1", sessionId: "s", executionId: "e", requestSummary: "更新技能，依据已有证据 3dfceb05e991484d8a89a1755489a232。", baseProfileVersion: "v1", currentProfileVersion: "v1", selectionSnapshot: {}, status: "validated", version: 2, stale: false, canConfirm: true, canCancel: true, retryable: false, createdAt: "now", items: [{ itemId: "i1", ordinal: 1, operation: "propose_claim_update", target: {}, expectedVersion: 1, before: { text: "Python" }, after: { text: "Python 3" }, evidenceIds: ["ev1"], status: "pending", receiptId: null, errorCode: null }] })),
  confirmProfileActionPlan: vi.fn(), cancelProfileActionPlan: vi.fn(), retryProfileActionPlan: vi.fn(),
}));

describe("ProfileActionPlanCard", () => {
  it("shows diff, evidence count and explicit confirmation", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileActionPlanCard workspaceId="w1" planId="p1" /></QueryClientProvider>);
    expect(await screen.findByText("建议的修改步骤")).toBeInTheDocument();
    expect(screen.getByText(/Python 3/)).toBeInTheDocument();
    expect(screen.getByText("来自简历 1 处")).toBeInTheDocument();
    expect(screen.getByText(/依据现有简历原文/)).toBeInTheDocument();
    expect(screen.queryByText(/3dfceb05/)).toBeNull();
    expect(screen.getByRole("button", { name: "确认执行" })).toBeEnabled();
  });
});
