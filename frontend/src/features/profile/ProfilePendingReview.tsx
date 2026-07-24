import { ClaimReview } from "./ClaimReview";
import type { ProfileClaimWorkspace, ProfileEvidence } from "./profileTypes";

export function ProfilePendingReview({
  workspaceId,
  snapshot,
  loading,
  onRefresh,
  onOpenEvidence,
}: {
  workspaceId: string;
  snapshot: ProfileClaimWorkspace | null;
  loading: boolean;
  onRefresh: () => Promise<unknown> | void;
  onOpenEvidence: (evidence: ProfileEvidence) => void;
}) {
  return <ClaimReview
    workspaceId={workspaceId}
    snapshot={snapshot}
    loading={loading}
    onRefresh={onRefresh}
    onOpenEvidence={onOpenEvidence}
  />;
}
