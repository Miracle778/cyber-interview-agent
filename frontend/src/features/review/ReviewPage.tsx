import { ReviewChat } from "./ReviewChat";
import { ReviewSessionList } from "./ReviewSessionList";
import { ReviewSetupPanel } from "./ReviewSetupPanel";

export function ReviewPage() {
  return (
    <section aria-labelledby="review-title">
      <h2 id="review-title">复习</h2>
      <ReviewSessionList />
      <ReviewChat />
      <ReviewSetupPanel />
    </section>
  );
}
