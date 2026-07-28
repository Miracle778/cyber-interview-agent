import { AlertTriangle, ArrowRight, CheckCircle2, FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { ProfileCardCategory, UnifiedProfile, UnifiedProfileCard } from "./profileTypes";

export type ProfileSupportFilter = "all" | "related" | "unsupported";

const categoryLabels: Partial<Record<ProfileCardCategory, string>> = {
  summary: "职业概况",
  direction: "求职方向",
  highlight: "个人亮点",
  experience: "工作经历",
  project: "项目经历",
  skill: "核心技能",
  education: "教育经历",
  certification: "证书",
  achievement: "成果",
  link: "个人链接",
};

function reviewCards(profile: UnifiedProfile) {
  return [
    ...(profile.summary ? [profile.summary] : []),
    ...profile.directions,
    ...profile.highlights,
    ...profile.experiences,
    ...profile.projects,
    ...profile.skills,
    ...profile.education,
    ...profile.certifications,
    ...profile.achievements,
    ...profile.links,
  ].filter((card) => ["related", "conflicted", "unsupported"].includes(card.supportStatus));
}

function statusLabel(card: UnifiedProfileCard) {
  return card.supportStatus === "unsupported" ? "缺少直接依据" : "相关内容待核对";
}

export function ProfileSupportReview({
  profile,
  loading,
  initialFilter,
  onEdit,
}: {
  profile: UnifiedProfile | null;
  loading: boolean;
  initialFilter: ProfileSupportFilter;
  onEdit: (card: UnifiedProfileCard) => void;
}) {
  const [filter, setFilter] = useState<ProfileSupportFilter>(initialFilter);
  useEffect(() => setFilter(initialFilter), [initialFilter]);
  const cards = useMemo(() => profile ? reviewCards(profile) : [], [profile]);
  const related = cards.filter((card) => card.supportStatus !== "unsupported");
  const unsupported = cards.filter((card) => card.supportStatus === "unsupported");
  const visible = filter === "all" ? cards : filter === "related" ? related : unsupported;

  if (loading) return <div className="profile-loading" role="status"><p>正在读取来源状态…</p></div>;

  return <TaskWorkspace className="profile-support-review" labelledBy="profile-support-review-title">
    <header className="profile-support-review__header">
      <div>
        <span>画像来源</span>
        <h2 id="profile-support-review-title">来源核对</h2>
        <p>集中处理已经进入画像、但来源发生变化的内容。这里与“待确认建议”相互独立。</p>
      </div>
      <div className="profile-support-review__summary">
        <span data-status="related"><strong>{related.length}</strong> 条相关内容待核对</span>
        <span data-status="unsupported"><strong>{unsupported.length}</strong> 条缺少直接依据</span>
      </div>
    </header>

    <nav className="profile-support-review__filters" aria-label="来源状态筛选">
      <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>全部 {cards.length}</button>
      <button type="button" aria-pressed={filter === "related"} onClick={() => setFilter("related")}>相关内容待核对 {related.length}</button>
      <button type="button" aria-pressed={filter === "unsupported"} onClick={() => setFilter("unsupported")}>缺少直接依据 {unsupported.length}</button>
    </nav>

    {visible.length ? <TaskWorkspacePane className="profile-support-review__list" aria-label="来源核对列表">
      {visible.map((card) => <article key={card.claimId} data-status={card.supportStatus}>
        <div className="profile-support-review__item-heading">
          <span>{categoryLabels[card.category] ?? "画像资料"}</span>
          <strong>{card.title}</strong>
          <small>{card.supportStatus === "unsupported" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}{statusLabel(card)}</small>
        </div>
        <p>{card.supportSummary}</p>
        {card.supportEvidence?.length ? <div className="profile-support-review__evidence">
          {card.supportEvidence.slice(0, 2).map((evidence) => <div key={evidence.evidenceId}>
            <span><FileText size={14} />{evidence.materialTitle} v{evidence.versionNumber} · {evidence.section}</span>
            <p>{evidence.excerpt}</p>
          </div>)}
        </div> : <div className="profile-support-review__missing">当前简历中没有可直接核对的原文。你可以补充来源、修改内容，或保留为本人确认。</div>}
        <button type="button" onClick={() => onEdit(card)}>查看并处理<ArrowRight size={15} /></button>
      </article>)}
    </TaskWorkspacePane> : <TaskWorkspacePane className="profile-support-review__empty" scroll={false}><CheckCircle2 size={28} /><h3>当前没有这类内容</h3><p>简历版本或画像来源变化后，需要核对的内容会集中显示在这里。</p></TaskWorkspacePane>}
  </TaskWorkspace>;
}
