import { useState } from "react";
import { CheckCircle2, FileCheck2, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../../shared/ui/Button";
import type {
  PublicationSection,
  RetrospectiveActionItem,
  RetrospectivePublicationDraft,
} from "./retrospectiveTypes";

const SECTIONS: Array<{ id: PublicationSection; label: string; detail: string }> = [
  { id: "basic_info", label: "基本信息", detail: "面试轮次、日期和结果" },
  { id: "confirmed_questions", label: "已确认问题", detail: "问题与改进参考表达" },
  { id: "selected_conclusions", label: "逐题结论", detail: "只发布正式分析结论" },
  { id: "confirmed_experiences", label: "已确认经历", detail: "只包含已确认的项目沉淀" },
  { id: "action_items", label: "后续行动", detail: "本场复盘的行动清单" },
  { id: "stable_links", label: "关联入口", detail: "复盘与求职目标的稳定引用" },
];

export function RetrospectiveActions({ actions, busy, draft, onDecision, onCreateDraft }: {
  actions: RetrospectiveActionItem[];
  busy: boolean;
  draft: RetrospectivePublicationDraft | null;
  onDecision: (action: RetrospectiveActionItem, decision: "completed" | "dismissed") => void;
  onCreateDraft: (sections: PublicationSection[]) => void;
}) {
  const [sections, setSections] = useState<PublicationSection[]>([
    "basic_info",
    "confirmed_questions",
    "selected_conclusions",
    "action_items",
  ]);
  const completed = actions.filter((item) => item.status === "completed").length;

  function toggleSection(section: PublicationSection) {
    setSections((current) => current.includes(section) ? current.filter((item) => item !== section) : [...current, section]);
  }

  return <section className="retrospective-actions" aria-labelledby="retrospective-actions-title">
    <div className="retrospective-actions__checklist">
      <header><div><p>把结论变成下一步</p><h3 id="retrospective-actions-title">行动清单</h3></div><strong>已完成 {completed} / {actions.length}</strong></header>
      <div className="retrospective-actions__rows">
        {actions.length ? actions.map((action) => <div key={action.id} className="retrospective-action-row" data-status={action.status}>
          <label>
            <input type="checkbox" aria-label={`完成：${action.title}`} checked={action.status === "completed"} disabled={busy || action.status === "dismissed"} onChange={() => onDecision(action, action.status === "completed" ? "dismissed" : "completed")} />
            <span><strong>{action.title}</strong><small>{action.detail}</small></span>
          </label>
          {action.status === "pending" ? <button type="button" disabled={busy} onClick={() => onDecision(action, "dismissed")}>暂不处理</button> : <span>{action.status === "completed" ? "已完成" : "已忽略"}</span>}
        </div>) : <div className="retrospective-actions__empty"><CheckCircle2 size={22} /><span>本场复盘暂时没有行动项</span></div>}
      </div>
    </div>
    <div className="retrospective-publication">
      <header><div><p>可选发布范围</p><h3>保存为 Knowledge 草稿</h3></div><FileCheck2 size={22} /></header>
      <div className="retrospective-publication__safety"><ShieldCheck size={18} /><span>发布内容不会包含原始转写、待确认推断题、聊天消息、Prompt 或模型原始响应。</span></div>
      <fieldset>
        <legend>选择要写入草稿的内容</legend>
        {SECTIONS.map((section) => <label key={section.id}><input type="checkbox" checked={sections.includes(section.id)} onChange={() => toggleSection(section.id)} /><span><strong>{section.label}</strong><small>{section.detail}</small></span></label>)}
      </fieldset>
      {draft ? <div className="retrospective-publication__success" role="status"><CheckCircle2 size={18} /><div><strong>Knowledge 草稿已生成</strong><span>{draft.title}</span><Link to="/knowledge">前往 Knowledge 查看</Link></div></div> : null}
      <Button disabled={!sections.length || busy} loading={busy} onClick={() => onCreateDraft(sections)}>生成 Knowledge 草稿</Button>
    </div>
  </section>;
}
