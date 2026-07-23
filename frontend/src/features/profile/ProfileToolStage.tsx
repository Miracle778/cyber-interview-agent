import { CheckCircle2, LoaderCircle, TriangleAlert } from "lucide-react";
import type { AgentEvent } from "../agent/agentTypes";

const labels: Record<string, string> = {
  list_personal_materials: "读取个人材料",
  search_personal_materials: "检索个人材料",
  read_personal_evidence: "读取证据",
  get_profile_claims: "读取已确认画像",
  get_profile_claim_evidence: "核对画像证据",
  compare_material_versions: "比较材料版本",
  search_active_knowledge: "检索已发布知识",
  get_profile_publication_status: "检查发布状态",
};

export function ProfileToolStage({ event, executionActive = true }: { event: AgentEvent; executionActive?: boolean }) {
  const payload = event.payload as { toolName?: string; status?: string; errorCode?: string };
  const failed = event.type === "agent.tool.failed";
  const interrupted = event.type === "agent.tool.started" && !executionActive;
  const running = event.type === "agent.tool.started" && executionActive;
  const Icon = failed ? TriangleAlert : running ? LoaderCircle : CheckCircle2;
  const action = labels[payload.toolName ?? ""] ?? "读取画像信息";
  return <div className={`profile-tool-stage${failed ? " profile-tool-stage--failed" : ""}`} role={failed ? "alert" : "status"}>
    <Icon size={16} className={running ? "spin" : undefined} aria-hidden="true" />
    <span>{running ? `正在${action}…` : failed ? `无法${action}，请重试` : interrupted ? `已停止${action}` : `已${action}`}</span>
  </div>;
}
