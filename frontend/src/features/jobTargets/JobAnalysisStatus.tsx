import { Pause, Play, Square } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { JobAnalysis } from "./jobTargetTypes";

const stageLabels: Record<string, string> = {
  extracting_requirements: "正在拆解岗位要求",
  mapping_profile: "正在核对个人资料",
  mapping_projects: "正在分析项目相关性",
  finalizing: "正在整理分析结果",
  waiting_for_review: "分析结果等待你确认",
  completed: "岗位分析已完成",
};

export function JobAnalysisStatus({ analysis, onControl }: { analysis: JobAnalysis; onControl?: (action: "pause" | "resume" | "terminate") => void }) {
  return <section className="job-analysis-status" aria-label="岗位分析进度">
    <div><span className={`job-analysis-status__dot is-${analysis.status}`} /><div><strong>{stageLabels[analysis.stage] ?? "岗位分析"}</strong><p>已完成 {analysis.progress.completed} / {analysis.progress.total}，结果会边处理边保存。</p></div></div>
    <dl>
      <div><dt>岗位要求</dt><dd>{analysis.savedOutputs.requirements} 条已保存</dd></div>
      <div><dt>项目匹配</dt><dd>{analysis.savedOutputs.projectMappings} 个已分析</dd></div>
      <div><dt>运行状态</dt><dd>{analysis.status === "running" ? "处理中" : analysis.status === "paused" ? "已暂停" : "可查看"}</dd></div>
    </dl>
    {onControl ? <div className="job-analysis-status__actions">
      {analysis.controls.canPause ? <Button variant="secondary" onClick={() => onControl("pause")}><Pause size={15} />暂停分析</Button> : null}
      {analysis.controls.canResume ? <Button variant="secondary" onClick={() => onControl("resume")}><Play size={15} />继续分析</Button> : null}
      {analysis.controls.canTerminate ? <Button variant="danger" onClick={() => onControl("terminate")}><Square size={15} />终止分析</Button> : null}
    </div> : null}
  </section>;
}
