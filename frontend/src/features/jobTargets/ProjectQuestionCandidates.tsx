import { useEffect, useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { ProjectQuestionCandidate } from "./jobTargetTypes";

const labels: Record<string, string> = {
  background_role: "背景与职责",
  architecture_solution: "方案设计",
  difficulty_problem_solving: "难点解决",
  outcome: "结果成效",
  tradeoff_failure_retrospective: "取舍与复盘",
  target_specific: "目标岗位追问",
};

const statuses: Record<ProjectQuestionCandidate["status"], string> = {
  review_pending: "待确认",
  confirmed: "已入库",
  ignored: "已忽略",
  duplicate: "已关联已有题",
};

export function ProjectQuestionCandidates({
  projectTitle,
  candidates,
  busy = false,
  onDecide,
  onBatchDecide,
  onEdit,
}: {
  projectTitle?: string;
  candidates: ProjectQuestionCandidate[];
  busy?: boolean;
  onDecide: (id: string, decision: "confirmed" | "ignored" | "duplicate") => void;
  onBatchDecide: (ids: string[], decision: "confirmed" | "ignored") => void;
  onEdit: (id: string, title: string, question: string) => void;
}) {
  const pending = useMemo(
    () => candidates.filter((item) => item.status === "review_pending"),
    [candidates],
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ title: "", question: "" });

  useEffect(() => {
    setSelected((current) => current.filter((id) => pending.some((item) => item.id === id)));
    if (editingId && !pending.some((item) => item.id === editingId)) setEditingId(null);
  }, [editingId, pending]);

  const allSelected = pending.length > 0 && selected.length === pending.length;
  const startEdit = (item: ProjectQuestionCandidate) => {
    setEditingId(item.id);
    setDraft({ title: item.question.title, question: item.question.question });
  };
  const toggle = (id: string) => setSelected((current) => current.includes(id)
    ? current.filter((value) => value !== id)
    : [...current, id]);

  return <section className="project-question-candidates">
    <header className="project-question-candidates__header">
      <div>
        <span>项目经历题</span>
        <h2>{projectTitle ? `围绕「${projectTitle}」准备追问` : "先核对候选题，再放入题库"}</h2>
        <p>每题都保留生成依据。确认后进入“项目经历题”，不会改写你的项目资料。</p>
      </div>
      <div className="project-question-candidates__summary" aria-label="候选题状态">
        <strong>{pending.length}</strong><span>待确认</span>
        <strong>{candidates.filter((item) => item.status === "confirmed").length}</strong><span>已入库</span>
      </div>
    </header>

    {pending.length ? <div className="project-question-candidates__bulk">
      <label><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : pending.map((item) => item.id))} /> 全选待确认</label>
      <span aria-live="polite">已选择 {selected.length} 道</span>
      <div>
        <Button variant="secondary" size="sm" disabled={!selected.length || busy} onClick={() => onBatchDecide(selected, "ignored")}>忽略选中</Button>
        <Button size="sm" loading={busy && selected.length > 0} disabled={!selected.length || busy} onClick={() => onBatchDecide(selected, "confirmed")}>确认选中并入库</Button>
      </div>
    </div> : null}

    <div className="project-question-candidates__list">
      {candidates.map((item) => {
        const isPending = item.status === "review_pending";
        const isEditing = editingId === item.id;
        return <article className={`project-question-candidate is-${item.status}`} key={item.id}>
          {isPending ? <label className="project-question-candidate__select"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} aria-label={`选择：${item.question.question}`} /></label> : <span className="project-question-candidate__select" aria-hidden="true" />}
          <div className="project-question-candidate__main">
            <div className="project-question-candidate__meta"><span>{labels[item.dimension] ?? item.dimension}</span><em>{statuses[item.status]}</em></div>
            {isEditing ? <div className="project-question-candidate__editor">
              <label>题目名称<input value={draft.title} maxLength={300} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} /></label>
              <label>面试问题<textarea value={draft.question} rows={4} maxLength={4000} onChange={(event) => setDraft((current) => ({ ...current, question: event.target.value }))} /></label>
              <div><Button variant="secondary" size="sm" onClick={() => setEditingId(null)} disabled={busy}>取消</Button><Button size="sm" loading={busy} disabled={!draft.title.trim() || !draft.question.trim()} onClick={() => onEdit(item.id, draft.title.trim(), draft.question.trim())}>保存修改</Button></div>
            </div> : <><h3>{item.question.question}</h3><details className="project-question-candidate__basis"><summary>查看生成依据</summary><div>
              <p><b>为什么生成</b>{item.question.rationale ?? "根据当前项目与本轮深挖内容整理。"}</p>
              {item.question.requirements?.length ? <p><b>本次参考的岗位重点</b>{item.question.requirements.map((value) => value.text).join("；")}</p> : null}
              {item.question.projectFacts?.length ? <p><b>可用项目事实</b>{item.question.projectFacts.map((value) => `“${value}”`).join("；")}</p> : null}
              {item.question.gaps?.length ? <p><b>仍需补充</b>{item.question.gaps.join("；")}</p> : null}
            </div></details></>}
          </div>
          {isPending && !isEditing ? <div className="project-question-candidate__actions">
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => startEdit(item)}>编辑</Button>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => onDecide(item.id, "ignored")}>忽略</Button>
            <Button size="sm" loading={busy} onClick={() => onDecide(item.id, "confirmed")}>确认入库</Button>
          </div> : null}
        </article>;
      })}
      {!candidates.length ? <div className="project-question-candidates__empty"><strong>还没有候选题</strong><p>完成一轮项目深挖后，系统会根据你已补充的事实生成可确认的问题。</p></div> : null}
    </div>
  </section>;
}
