import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, CircleAlert } from "lucide-react";
import { listAgentSessions } from "../agent/agentApi";
import { listActions } from "../agent/hitlApi";
import { getDraft } from "../knowledge/draftApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import type { ReviewQuestion } from "./reviewTypes";

interface FlowSummaryProps {
  healthStatus: "checking" | "connected" | "disconnected";
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  indexedCount: number | null;
}

export function FlowSummary({
  healthStatus,
  workspace,
  draftQuestion,
  indexedCount,
}: FlowSummaryProps) {
  const [reportState, setReportState] = useState<"none" | "pending" | "published">("none");

  useEffect(() => {
    if (!workspace) {
      setReportState("none");
      return;
    }
    let cancelled = false;
    void listAgentSessions(workspace.id).then(async (sessions) => {
      const session = sessions.find((item) => item.graphId === "review.single");
      if (!session) return "none" as const;
      const actions = await listActions(workspace.id, { sessionId: session.id });
      const draftId = actions.at(-1)?.preview.draftId;
      if (typeof draftId !== "string") return "none" as const;
      const draft = await getDraft(draftId);
      return draft.status === "published" ? "published" as const : "pending" as const;
    }).then((state) => {
      if (!cancelled) setReportState(state);
    }).catch(() => {
      if (!cancelled) setReportState("none");
    });
    return () => { cancelled = true; };
  }, [workspace]);

  const hasReport = reportState !== "none";
  const reportConfirmed = reportState === "published";
  const items = [
    {
      label: healthStatus === "connected" ? "后端连接：已连接" : healthStatus === "disconnected" ? "后端连接：未连接" : "后端连接：检查中",
      state: healthStatus === "connected" ? "done" : healthStatus === "disconnected" ? "error" : "active",
    },
    { label: workspace ? "Workspace：已就绪" : "Workspace：待初始化", state: workspace ? "done" : "pending" },
    { label: draftQuestion ? "题库草稿：已生成" : "题库草稿：待生成", state: draftQuestion ? "done" : "pending" },
    {
      label: reportConfirmed ? "复习报告：已确认" : hasReport ? "复习报告：待确认" : "复习报告：待生成",
      state: reportConfirmed ? "done" : hasReport ? "active" : "pending",
    },
    {
      label: indexedCount === null ? "Vault 索引：待扫描" : `Vault 索引：已扫描 ${indexedCount} 个文档`,
      state: indexedCount === null ? "pending" : "done",
    },
  ];

  const nextStep = getNextStepText({
    healthStatus,
    workspace,
    draftQuestion,
    hasReport,
    reportConfirmed,
    indexedCount,
  });

  return (
    <section className="flow-summary" aria-label="流程状态">
      <div className="flow-summary__header">
        <p className="flow-summary__eyebrow">当前进度</p>
        <h2>复习准备</h2>
      </div>
      <ul className="flow-summary__list">
        {items.map((item) => (
          <li key={item.label} data-state={item.state}>
            {item.state === "done" ? (
              <CheckCircle2 size={16} aria-hidden="true" />
            ) : item.state === "error" ? (
              <CircleAlert size={16} aria-hidden="true" />
            ) : (
              <Circle size={16} aria-hidden="true" />
            )}
            <span>{item.label}</span>
          </li>
        ))}
      </ul>
      <p className="flow-summary__next">
        <ArrowRight size={16} aria-hidden="true" />
        {nextStep}
      </p>
    </section>
  );
}

function getNextStepText({
  healthStatus,
  workspace,
  draftQuestion,
  hasReport,
  reportConfirmed,
  indexedCount,
}: FlowSummaryProps & { hasReport: boolean; reportConfirmed: boolean }) {
  if (healthStatus === "disconnected") return "下一步：启动后端服务";
  if (!workspace) return "下一步：初始化工作区";
  if (!draftQuestion) return "下一步：上传资料生成题库草稿";
  if (!hasReport) return "下一步：发送回答生成复习报告";
  if (!reportConfirmed) return "下一步：确认报告";
  if (indexedCount === null) return "下一步：重新扫描 Vault";
  return "下一步：继续下一轮复习";
}
