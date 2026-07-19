import { ReviewConversation } from "./ReviewConversation";
import type { ReviewRound as ReviewRoundValue } from "./reviewTypes";

export function ReviewRound({ round, onSubmit, onSkip, onCancel, busy }: { round: ReviewRoundValue; onSubmit: (value: string, configuration: { providerModelId: string; reasoningEffort: "none" | "low" | "medium" | "high" }) => Promise<unknown>; onSkip: () => void; onCancel: () => void; busy: boolean }) {
  return <ReviewConversation round={round} optimisticMessage={null} busy={busy} onSubmit={onSubmit} onSkip={onSkip} onCancel={onCancel} onRetry={() => undefined} />;
}
