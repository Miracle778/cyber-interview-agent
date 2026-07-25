import type { ReactNode } from "react";
import type { JobTarget } from "./jobTargetTypes";

export type JobTargetTab = "overview" | "requirements" | "deep-dive" | "review";

export function JobTargetWorkspace({ target, tab, onTab, children }: { target: JobTarget; tab: JobTargetTab; onTab: (tab: JobTargetTab) => void; children: ReactNode }) {
  return <section className="job-target-workspace"><header className="job-target-workspace__header"><div><span>求职目标</span><h1>{target.roleName || "正在从岗位描述识别岗位信息"}</h1><p>{[target.companyName, target.seniority].filter(Boolean).join(" · ") || "岗位描述已保存，识别完成后可核对"}</p></div><em>{target.lifecycleStatus === "active" ? "准备中" : target.lifecycleStatus === "archived" ? "已归档" : "回收站"}</em></header><nav className="job-target-workspace__tabs" aria-label="求职目标功能"><button aria-current={tab === "overview" ? "page" : undefined} onClick={() => onTab("overview")}>准备总览</button><button aria-current={tab === "requirements" ? "page" : undefined} onClick={() => onTab("requirements")}>岗位要求</button><button aria-current={tab === "deep-dive" ? "page" : undefined} onClick={() => onTab("deep-dive")}>项目深挖</button><button aria-current={tab === "review" ? "page" : undefined} onClick={() => onTab("review")}>项目经历题</button></nav><div className="job-target-workspace__content">{children}</div></section>;
}
