import { CheckCircle2, LoaderCircle, TriangleAlert } from "lucide-react";
import type { AgentEvent } from "../agent/agentTypes";

const labels: Record<string, string> = {
  list_personal_materials: "查看简历",
  search_personal_materials: "查找简历内容",
  read_personal_evidence: "查看简历原文",
  read_personal_evidence_batch: "查看简历原文",
  get_profile_claims: "查看已确认信息",
  get_profile_claim_evidence: "核对信息来源",
  compare_material_versions: "比较简历版本",
};

export function ProfileToolStage({ event, executionActive = true }: { event: AgentEvent; executionActive?: boolean }) {
  const payload = event.payload as { toolName?: string; status?: string; errorCode?: string };
  const failed = event.type === "agent.tool.failed";
  const interrupted = event.type === "agent.tool.started" && !executionActive;
  const running = event.type === "agent.tool.started" && executionActive;
  const Icon = failed ? TriangleAlert : running ? LoaderCircle : CheckCircle2;
  const action = labels[payload.toolName ?? ""] ?? "查看简历信息";
  return <div className={`profile-tool-stage${failed ? " profile-tool-stage--failed" : ""}`} role={failed ? "alert" : "status"}>
    <Icon size={16} className={running ? "spin" : undefined} aria-hidden="true" />
    <span>{running ? `正在${action}…` : failed ? `无法${action}，请重试` : interrupted ? `已停止${action}` : `已${action}`}</span>
  </div>;
}
