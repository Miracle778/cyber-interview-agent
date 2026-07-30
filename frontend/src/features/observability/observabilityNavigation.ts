import type { ExecutionSummary } from "./observabilityTypes";

const CURATION_GRAPHS = new Set(["question.curate", "question.revise"]);
const REVIEW_ROUND_GRAPHS = new Set(["review.round"]);

function appendRouteParams(
  route: string,
  params: Record<string, string>,
) {
  const [pathname, currentQuery = ""] = route.split("?", 2);
  const query = new URLSearchParams(currentQuery);
  Object.entries(params).forEach(([key, value]) => query.set(key, value));
  return `${pathname}?${query.toString()}`;
}

export function executionBusinessDestination(
  execution: ExecutionSummary,
  returnTo: string,
) {
  if (!execution.route) return { to: "", exact: false };
  if (CURATION_GRAPHS.has(execution.graphId)) {
    return {
      to: appendRouteParams(execution.route, {
        section: "catalog",
        curationSessionId: execution.sessionId,
        returnTo,
      }),
      exact: true,
    };
  }
  if (REVIEW_ROUND_GRAPHS.has(execution.graphId)) {
    return {
      to: appendRouteParams(execution.route, {
        section: "practice",
        reviewSessionId: execution.sessionId,
        returnTo,
      }),
      exact: true,
    };
  }
  return {
    to: appendRouteParams(execution.route, { returnTo }),
    exact: false,
  };
}
