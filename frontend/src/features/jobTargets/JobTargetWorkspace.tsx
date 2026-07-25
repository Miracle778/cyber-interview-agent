import type { ReactNode } from "react";
import type { JobAnalysis, JobTarget } from "./jobTargetTypes";

export type JobTargetTab = "overview" | "requirements" | "deep-dive" | "review";

export function getTargetIdentity(target: JobTarget, analysis?: JobAnalysis | null) {
  if (target.roleName) return {
    title: target.roleName,
    description: [target.companyName, target.seniority].filter(Boolean).join(" · ") || "岗位描述已保存，可继续完善准备计划。",
    badge: target.lifecycleStatus === "active" ? "准备中" : target.lifecycleStatus === "archived" ? "已归档" : "回收站",
  };
  if (analysis?.status === "running") return { title: "正在识别岗位信息", description: "已保存岗位描述，正在提取岗位、公司和经验范围。", badge: "识别中" };
  if (analysis?.status === "paused") return { title: "岗位信息识别已暂停", description: "已保存岗位描述；恢复分析后会继续提取岗位信息。", badge: "已暂停" };
  if (analysis?.status === "failed") return { title: "岗位信息识别失败", description: "岗位描述仍已保存；可以重新分析，或手动补充岗位信息。", badge: "需处理" };
  if (analysis?.status === "terminated") return { title: "岗位信息识别已终止", description: "岗位描述仍已保存；可以重新分析，或手动补充岗位信息。", badge: "已终止" };
  if (analysis?.status === "review_pending") return { title: "岗位信息待补充", description: "岗位要求已整理完成；这份描述没有足够明确的岗位名称或经验范围，可手动补充后继续准备。", badge: "待补充" };
  return { title: "等待岗位描述", description: "添加岗位描述后，系统会识别岗位信息并整理需要确认的要求。", badge: "待开始" };
}

export function JobTargetWorkspace({ target, analysis, tab, onTab, children }: { target: JobTarget; analysis?: JobAnalysis | null; tab: JobTargetTab; onTab: (tab: JobTargetTab) => void; children: ReactNode }) {
  const identity = getTargetIdentity(target, analysis);
  return <section className="job-target-workspace"><header className="job-target-workspace__header"><div><span>求职目标</span><h1>{identity.title}</h1><p>{identity.description}</p></div><em>{identity.badge}</em></header><nav className="job-target-workspace__tabs" aria-label="求职目标功能"><button aria-current={tab === "overview" ? "page" : undefined} onClick={() => onTab("overview")}>准备总览</button><button aria-current={tab === "requirements" ? "page" : undefined} onClick={() => onTab("requirements")}>岗位要求</button><button aria-current={tab === "deep-dive" ? "page" : undefined} onClick={() => onTab("deep-dive")}>项目深挖</button><button aria-current={tab === "review" ? "page" : undefined} onClick={() => onTab("review")}>项目经历题</button></nav><div className="job-target-workspace__content">{children}</div></section>;
}
