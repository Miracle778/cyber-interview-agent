import { ArrowRight, CheckCircle2, Circle, CircleAlert } from "lucide-react";
import type { WorkspaceConfig } from "../settings/settingsApi";
import type { ReviewQuestion } from "./reviewTypes";

interface FlowSummaryProps {
  healthStatus: "checking" | "connected" | "disconnected";
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  reportConfirmed: boolean;
  indexedCount: number | null;
}

export function FlowSummary({
  healthStatus,
  workspace,
  draftQuestion,
  latestReportMarkdown,
  reportConfirmed,
  indexedCount,
}: FlowSummaryProps) {
  const items = [
    {
      label: healthStatus === "connected" ? "后端连接：已连接" : healthStatus === "disconnected" ? "后端连接：未连接" : "后端连接：检查中",
      state: healthStatus === "connected" ? "done" : healthStatus === "disconnected" ? "error" : "active",
    },
    { label: workspace ? "工作区：已就绪" : "工作区：待配置", state: workspace ? "done" : "pending" },
    { label: draftQuestion ? "题库草稿：已生成" : "题库草稿：待生成", state: draftQuestion ? "done" : "pending" },
    {
      label: reportConfirmed ? "复习报告：已确认" : latestReportMarkdown ? "复习报告：待确认" : "复习报告：待生成",
      state: reportConfirmed ? "done" : latestReportMarkdown ? "active" : "pending",
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
    latestReportMarkdown,
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
  latestReportMarkdown,
  reportConfirmed,
  indexedCount,
}: FlowSummaryProps) {
  if (healthStatus === "disconnected") return "下一步：启动后端服务";
  if (!workspace) return "下一步：初始化工作区";
  if (!draftQuestion) return "下一步：上传资料生成题库草稿";
  if (!latestReportMarkdown) return "下一步：发送回答生成复习报告";
  if (!reportConfirmed) return "下一步：确认报告";
  if (indexedCount === null) return "下一步：重新扫描 Vault";
  return "下一步：继续下一轮复习";
}
