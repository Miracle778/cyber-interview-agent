import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileActionPlanCard } from "./ProfileActionPlanCard";

vi.mock("./profileApi", () => ({
  getProfileActionPlan: vi.fn(async () => ({ id: "p1", workspaceId: "w1", sessionId: "s", executionId: "e", requestSummary: "更新技能", baseProfileVersion: "v1", currentProfileVersion: "v1", selectionSnapshot: {}, status: "validated", version: 2, stale: false, canConfirm: true, canCancel: true, retryable: false, createdAt: "now", items: [{ itemId: "i1", ordinal: 1, operation: "propose_claim_update", target: {}, expectedVersion: 1, before: { text: "Python" }, after: { text: "Python 3" }, evidenceIds: ["ev1"], status: "pending", receiptId: null, errorCode: null }] })),
  confirmProfileActionPlan: vi.fn(), cancelProfileActionPlan: vi.fn(), retryProfileActionPlan: vi.fn(),
}));

describe("ProfileActionPlanCard", () => {
  it("shows diff, evidence count and explicit confirmation", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ProfileActionPlanCard workspaceId="w1" planId="p1" /></QueryClientProvider>);
    expect(await screen.findByText("画像修改方案")).toBeInTheDocument();
    expect(screen.getByText(/Python 3/)).toBeInTheDocument();
    expect(screen.getByText("证据 1 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认执行" })).toBeEnabled();
  });
});
