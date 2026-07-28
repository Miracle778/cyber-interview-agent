import { Check, ChevronDown, ChevronUp, Pause, Play, Square } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { JobAnalysis } from "./jobTargetTypes";
import { useEffect, useState } from "react";
import { formatBeijingTime, formatElapsedSeconds } from "../../shared/time";

const stageLabels: Record<string, string> = {
  extracting_requirements: "正在拆解岗位要求",
  mapping_profile: "正在核对个人资料",
  mapping_projects: "正在分析项目相关性",
  finalizing: "正在整理分析结果",
  waiting_for_review: "分析结果等待你确认",
  completed: "岗位分析已完成",
};

const visibleStages = [
  { key: "extracting_requirements", label: "读取岗位内容", description: "识别岗位信息和明确要求" },
  { key: "mapping_profile", label: "核对个人资料", description: "查找已有经历与能力依据" },
  { key: "mapping_projects", label: "分析项目相关性", description: "判断重点项目与岗位的匹配度" },
  { key: "finalizing", label: "整理分析结果", description: "汇总要求、项目和准备建议" },
  { key: "waiting_for_review", label: "等待你确认", description: "结果已保存，等待人工核对" },
] as const;

function getVisibleStageState(analysis: JobAnalysis, index: number) {
  if (analysis.status === "completed" || analysis.stage === "completed") return "completed";
  const currentIndex = visibleStages.findIndex((stage) => stage.key === analysis.stage);
  if (currentIndex < 0) return index === 0 ? "active" : "pending";
  if (index < currentIndex) return "completed";
  if (index > currentIndex) return "pending";
  return analysis.status === "paused" ? "paused" : analysis.stage === "waiting_for_review" ? "completed" : "active";
}

export function JobAnalysisStatus({ analysis, onControl, onOpenRequirements, onOpenProjects }: { analysis: JobAnalysis; onControl?: (action: "pause" | "resume" | "terminate") => void; onOpenRequirements?: () => void; onOpenProjects?: () => void }) {
  const isActive = analysis.status === "running" || analysis.status === "paused";
  const [detailsOpen, setDetailsOpen] = useState(isActive);
  useEffect(() => {
    if (isActive) setDetailsOpen(true);
  }, [analysis.id, isActive]);
  const currentElapsed = formatElapsedSeconds(analysis.timing.currentElapsedMs / 1000);
  const cumulativeElapsed = formatElapsedSeconds(analysis.timing.cumulativeElapsedMs / 1000);
  const latestProgress = analysis.latestProgressAt ? formatBeijingTime(analysis.latestProgressAt, false) : null;

  return <section className="job-analysis-status" aria-label="岗位分析进度">
    <div className="job-analysis-status__summary"><span className={`job-analysis-status__dot is-${analysis.status}`} /><div><strong>{stageLabels[analysis.stage] ?? "岗位分析"}</strong><p>已完成 {analysis.progress.completed} / {analysis.progress.total}，每一步结果都会自动保存。</p></div></div>
    <div className="job-analysis-status__links">
      <button type="button" onClick={onOpenRequirements}><span>岗位要求</span><strong>{analysis.savedOutputs.requirements} 条已保存</strong></button>
      <button type="button" onClick={onOpenProjects}><span>项目匹配</span><strong>{analysis.savedOutputs.projectMappings} 个已分析</strong></button>
      <button type="button" className="job-analysis-status__toggle" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((value) => !value)}>
        <span>分析过程</span>
        <strong>{detailsOpen ? "收起过程" : isActive ? "查看实时进展" : "查看处理过程"}{detailsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</strong>
      </button>
    </div>
    {detailsOpen ? <div className="job-analysis-status__process">
      <ol className="job-analysis-status__timeline" aria-label="岗位分析步骤">
        {visibleStages.map((stage, index) => {
          const state = getVisibleStageState(analysis, index);
          return <li key={stage.key} data-state={state}>
            <span className="job-analysis-status__step-marker">{state === "completed" ? <Check size={15} /> : index + 1}</span>
            <div><strong>{stage.label}</strong><small>{state === "active" ? "正在处理" : state === "paused" ? "已暂停，可继续" : state === "completed" ? "已完成" : stage.description}</small></div>
          </li>;
        })}
      </ol>
      <div className="job-analysis-status__facts">
        <span>本次已运行 <strong>{currentElapsed}</strong></span>
        <span>累计处理 <strong>{cumulativeElapsed}</strong></span>
        <span>最近更新 <strong>{latestProgress ? `${latestProgress}（北京时间）` : "暂无记录"}</strong></span>
        <span>{analysis.progress.activeWorkers > 0 ? `${analysis.progress.activeWorkers} 个任务正在处理` : "当前没有运行中的任务"}</span>
      </div>
    </div> : null}
    {onControl ? <div className="job-analysis-status__actions">
      {analysis.controls.canPause ? <Button variant="secondary" onClick={() => onControl("pause")}><Pause size={15} />暂停分析</Button> : null}
      {analysis.controls.canResume ? <Button variant="secondary" onClick={() => onControl("resume")}><Play size={15} />继续分析</Button> : null}
      {analysis.controls.canTerminate ? <Button variant="danger" onClick={() => onControl("terminate")}><Square size={15} />终止分析</Button> : null}
    </div> : null}
  </section>;
}
