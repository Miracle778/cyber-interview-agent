import { CheckCircle2, CircleAlert, FileText, FolderKanban, ListChecks } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { JobAnalysisStatus } from "./JobAnalysisStatus";
import type { JobAnalysis, JobTarget, TargetReadiness } from "./jobTargetTypes";

const labels: Record<string, string> = { requirements_pending: "先确认岗位要求", project_selection_pending: "选择重点准备项目", deep_dive_in_progress: "继续项目深挖", high_risk_open: "处理尚未掌握的项目问题", core_preparation_complete: "核心准备已完成" };

export function JobTargetOverview({ target, readiness, analysis, onEditJd, onStartAnalysis, onControl }: { target: JobTarget; readiness?: TargetReadiness; analysis?: JobAnalysis | null; onEditJd: () => void; onStartAnalysis: () => void; onControl: (action: "pause" | "resume" | "terminate") => void }) {
  return <div className="job-target-overview"><section className="job-target-overview__lead"><div><span>下一步</span><h2>{labels[readiness?.status ?? "requirements_pending"]}</h2><p>围绕岗位要求核对个人经历，再把重点项目练成能讲、能追问、能复盘的面试答案。</p></div>{target.currentDocumentVersionId ? <Button onClick={onStartAnalysis}>重新分析岗位</Button> : <Button onClick={onEditJd}><FileText size={16} />添加岗位描述</Button>}</section>{analysis ? <JobAnalysisStatus analysis={analysis} onControl={onControl} /> : null}<section className="job-target-overview__steps"><article><ListChecks /><div><strong>1. 看懂岗位</strong><p>{readiness?.requirements ?? 0} 条岗位要求</p></div></article><article><FolderKanban /><div><strong>2. 选重点项目</strong><p>1 个核心项目，最多 2 个补充项目</p></div></article><article>{readiness?.status === "core_preparation_complete" ? <CheckCircle2 /> : <CircleAlert />}<div><strong>3. 练项目问题</strong><p>确认候选题后进入项目经历题分类</p></div></article></section></div>;
}
