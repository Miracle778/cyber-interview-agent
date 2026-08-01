import { CalendarDays, ChevronRight, MessageSquareText } from "lucide-react";
import type { JobTarget } from "../jobTargets/jobTargetTypes";
import type { InterviewRetrospective, RetrospectiveOutcome } from "./retrospectiveTypes";

const OUTCOME_LABELS: Record<RetrospectiveOutcome, string> = {
  pending: "等待结果",
  passed: "已通过",
  failed: "未通过",
  cancelled: "已取消",
  unrecorded: "未记录结果",
};

function businessDate(value: string | null) {
  return value ? value.replaceAll("-", "/") : "日期未记录";
}

export function RetrospectiveList({
  items,
  targets,
  selectedId,
  loading,
  onSelect,
}: {
  items: InterviewRetrospective[];
  targets: JobTarget[];
  selectedId?: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  const targetById = new Map(targets.map((target) => [target.id, target]));
  if (loading) return <div className="retrospective-list__state" role="status">正在读取复盘记录</div>;
  if (!items.length) return <div className="retrospective-list__state"><MessageSquareText size={28} /><strong>这里还没有复盘</strong><p>新建后，原始文字和整理进度会保存在当前工作区。</p></div>;
  return (
    <div className="retrospective-list" aria-label="面试复盘列表">
      {items.map((item) => {
        const target = targetById.get(item.jobTargetId);
        return (
          <button type="button" key={item.id} data-selected={item.id === selectedId} onClick={() => onSelect(item.id)}>
            <span className="retrospective-list__icon"><MessageSquareText size={19} /></span>
            <div>
              <strong>{item.title}</strong>
              <p>{[target?.companyName, target?.roleName, item.roundLabel].filter(Boolean).join(" / ")}</p>
              <span><CalendarDays size={14} /> {businessDate(item.interviewDate)}<em data-outcome={item.outcome}>{OUTCOME_LABELS[item.outcome]}</em></span>
            </div>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
