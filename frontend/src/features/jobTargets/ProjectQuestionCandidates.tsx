import { Button } from "../../shared/ui/Button";
import type { ProjectQuestionCandidate } from "./jobTargetTypes";

const labels: Record<string, string> = { background_role: "背景与职责", architecture_solution: "方案设计", difficulty_problem_solving: "难点解决", outcome: "结果成效", tradeoff_failure_retrospective: "取舍与复盘", target_specific: "目标岗位追问" };

export function ProjectQuestionCandidates({ candidates, onDecide }: { candidates: ProjectQuestionCandidate[]; onDecide: (id: string, decision: "confirmed" | "ignored" | "duplicate") => void }) {
  return <section className="project-question-candidates"><header><h3>项目经历候选题</h3><p>确认后才会进入项目经历题分类；这里不会自动发布。</p></header>{candidates.map((item) => <article key={item.id}><span>{labels[item.dimension] ?? item.dimension}</span><strong>{item.question.question}</strong><em>{item.status === "review_pending" ? "待确认" : item.status === "confirmed" ? "已确认" : "已忽略"}</em>{item.status === "review_pending" ? <div><Button variant="secondary" onClick={() => onDecide(item.id, "ignored")}>忽略</Button><Button onClick={() => onDecide(item.id, "confirmed")}>确认入库</Button></div> : null}</article>)}</section>;
}
