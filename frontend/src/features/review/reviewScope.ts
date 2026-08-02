import type { ReviewRound } from "./reviewTypes";

export function reviewScopeTitle(round: Pick<ReviewRound, "settings">): string {
  const scope = round.settings.question_scope ?? "ordinary";
  if (scope === "job_target") return round.settings.scope_label ? `岗位专项 · ${round.settings.scope_label}` : "岗位专项";
  if (scope === "project") return round.settings.scope_label ? `项目专项 · ${round.settings.scope_label}` : "项目专项";
  return "自主复习";
}
