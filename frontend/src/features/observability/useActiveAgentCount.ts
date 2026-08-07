import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { listObservabilityExecutions } from "./observabilityApi";
import { useObservabilityEvents } from "./useObservabilityEvents";


const ACTIVE_FILTERS = {
  search: "",
  status: "running",
  agentName: "",
  includeSystemAgents: false,
};

export function useActiveAgentCount(workspaceId: string | null): number {
  const query = useQuery({
    queryKey: ["agent-observability", "active-count", workspaceId],
    enabled: Boolean(workspaceId),
    queryFn: ({ signal }) => listObservabilityExecutions(
      workspaceId!,
      ACTIVE_FILTERS,
      signal,
    ),
    refetchInterval: 10_000,
  });
  const refresh = useCallback(() => {
    void query.refetch();
  }, [query.refetch]);
  useObservabilityEvents(workspaceId, refresh);
  return query.data?.total ?? 0;
}
