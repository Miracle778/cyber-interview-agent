import { useState } from "react";
import { AlertTriangle, ArrowRight, BookOpenCheck, BriefcaseBusiness, CheckCircle2, ChevronDown, FileUp, Pencil, Plus, Sparkles, Target, UserRound } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { ProfileActionableGaps } from "./ProfileActionableGaps";
import { ProfileSourceBadge } from "./ProfileSourceBadge";
import type { ProfileCardCategory, UnifiedProfile, UnifiedProfileCard } from "./profileTypes";

const sectionLabels: Partial<Record<ProfileCardCategory, string>> = {
  experience: "工作经历",
  project: "项目经历",
  education: "教育经历",
  certification: "证书",
  achievement: "成果",
};

type ProfileView = "overview" | "experience" | "project" | "education" | "achievement";

function textList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function cardDetails(card: UnifiedProfileCard) {
  const value = card.value;
  if (card.category === "project") return [
    ...textList(value.key_actions),
    ...textList(value.responsibilities),
    ...textList(value.results),
  ].slice(0, 3);
  if (card.category === "experience") return [
    ...textList(value.responsibilities),
    ...textList(value.achievements),
  ].slice(0, 3);
  if (card.category === "education") return textList(value.highlights).slice(0, 3);
  if (card.category === "achievement" && typeof value.description === "string") return [value.description];
  return [];
}

function supportLabel(card: UnifiedProfileCard) {
  if (card.supportStatus === "related") return "相关内容待核对";
  if (card.supportStatus === "manual") return "本人确认";
  if (card.supportStatus === "conflicted") return "来源有冲突";
  if (card.supportStatus === "unsupported") return "缺少直接依据";
  return null;
}

function ProfileCard({ card, onEdit }: { card: UnifiedProfileCard; onEdit: (card: UnifiedProfileCard) => void }) {
  const details = cardDetails(card);
  const technologies = card.category === "project" ? textList(card.value.tech_stack) : [];
  const support = supportLabel(card);
  const needsReview = card.supportStatus === "unsupported" || card.supportStatus === "related" || card.supportStatus === "conflicted";
  return <article className="unified-profile-card" data-support={needsReview ? card.supportStatus : undefined}>
    <header>
      <div><h3>{card.title}</h3>{support ? <span className="unified-profile-card__support" data-status={card.supportStatus}>{needsReview ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}{support}</span> : null}{card.subtitle ? <p>{card.subtitle}</p> : null}</div>
      <button type="button" aria-label={`编辑${card.title}`} onClick={() => onEdit(card)}><Pencil size={16} /></button>
    </header>
    {typeof card.value.background === "string" ? <p className="unified-profile-card__intro">{card.value.background}</p> : null}
    {details.length ? <ul>{details.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : null}
    {technologies.length ? <div className="unified-profile-card__tags">{technologies.map((item) => <span key={item}>{item}</span>)}</div> : null}
    <footer>
      <div>{card.sources.length ? card.sources.slice(0, 2).map((source, index) => <ProfileSourceBadge key={`${source.sourceKind}-${index}`} source={source} />) : <span className="profile-source-badge">本人补充</span>}</div>
      {card.usedIn.length ? <span>用于 {card.usedIn.map((item) => item.title).join("、")}</span> : null}
    </footer>
  </article>;
}

function ProfileSection({
  category,
  cards,
  onCreate,
  onEdit,
  onShowAll,
  optionalCreate,
  createLabel,
}: {
  category: ProfileCardCategory;
  cards: UnifiedProfileCard[];
  onCreate: (category: ProfileCardCategory) => void;
  onEdit: (card: UnifiedProfileCard) => void;
  onShowAll?: () => void;
  optionalCreate?: { category: ProfileCardCategory; label: string };
  createLabel?: string;
}) {
  return <section className="unified-profile-section" aria-labelledby={`profile-${category}-title`}>
    <header>
      <div><h2 id={`profile-${category}-title`}>{sectionLabels[category] ?? category}</h2><span>{cards.length} 条</span></div>
      <div className="unified-profile-section__actions">
        {onShowAll ? <button type="button" onClick={onShowAll}>查看全部<ArrowRight size={14} /></button> : null}
        {optionalCreate ? <button className="unified-profile-section__optional-action" type="button" onClick={() => onCreate(optionalCreate.category)}><Plus size={15} />{optionalCreate.label}</button> : null}
        <button type="button" onClick={() => onCreate(category)}><Plus size={16} />{createLabel ?? "添加"}</button>
      </div>
    </header>
    {cards.length ? <div className="unified-profile-section__cards">{cards.map((card) => <ProfileCard key={card.claimId} card={card} onEdit={onEdit} />)}</div>
      : <button className="unified-profile-section__empty" type="button" onClick={() => onCreate(category)}><Plus size={17} />添加{sectionLabels[category]}</button>}
  </section>;
}

export function UnifiedProfileOverview({
  profile,
  loading,
  onUpload,
  onCreate,
  onEdit,
  onOpenPending,
  onOpenSupportReview,
  onSetPrimaryDirection,
  onCreateJobTarget,
  onOpenReview,
}: {
  profile: UnifiedProfile | null;
  loading: boolean;
  onUpload: () => void;
  onCreate: (category?: ProfileCardCategory) => void;
  onEdit: (card: UnifiedProfileCard) => void;
  onOpenPending: () => void;
  onOpenSupportReview: (filter: "related" | "unsupported") => void;
  onSetPrimaryDirection: (claimId: string) => void;
  onCreateJobTarget: () => void;
  onOpenReview: () => void;
}) {
  const [activeView, setActiveView] = useState<ProfileView>("overview");
  const [skillsExpanded, setSkillsExpanded] = useState(false);

  if (loading) return <div className="profile-loading" role="status"><span className="profile-loading__bar" /><span className="profile-loading__bar" /><p>正在读取个人画像…</p></div>;
  if (!profile) return null;

  const cardCount = profile.experiences.length + profile.projects.length + profile.skills.length + profile.education.length + profile.certifications.length + profile.achievements.length;
  const allCards = [
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
  ];
  const unsupportedCount = allCards.filter((card) => card.supportStatus === "unsupported").length;
  const relatedCount = allCards.filter((card) => card.supportStatus === "related" || card.supportStatus === "conflicted").length;
  const primaryDirection = profile.directions.find((item) => item.claimId === profile.primaryDirectionClaimId) ?? profile.directions[0] ?? null;
  const heroCard = primaryDirection ?? profile.summary;
  const views: Array<{ key: ProfileView; label: string; count: number }> = [
    { key: "overview", label: "概览", count: cardCount },
    { key: "experience", label: "工作经历", count: profile.experiences.length },
    { key: "project", label: "项目经历", count: profile.projects.length },
    { key: "education", label: "教育经历", count: profile.education.length },
    { key: "achievement", label: "证书与成果", count: profile.certifications.length + profile.achievements.length },
  ];

  if (!profile.isUsable && !profile.summary && !profile.directions.length && !profile.highlights.length) {
    return <section className="unified-profile-empty">
      <span><UserRound size={30} /></span>
      <h2>从这里建立你的个人画像</h2>
      <p>画像是你确认过的经历、项目和技能，会被后续的岗位分析、简历优化和面试训练共同使用。</p>
      <div><Button onClick={onUpload}><FileUp size={17} />上传简历自动整理</Button><Button variant="secondary" onClick={() => onCreate("project")}><Pencil size={17} />从空白开始</Button></div>
      <small>两种方式可以同时使用，所有内容都能随时修改。</small>
    </section>;
  }

  const attentionCount = relatedCount + unsupportedCount + profile.pendingCount;

  return <main className="unified-profile">
    <section className="unified-profile-hero">
      <div className="unified-profile-hero__content">
        <span>我的职业资产</span>
        <h2>{heroCard?.title ?? "尚未设置职业定位"}</h2>
        {heroCard && supportLabel(heroCard) ? <span className="unified-profile-card__support" data-status={heroCard.supportStatus}>{heroCard.supportStatus === "manual" ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{supportLabel(heroCard)}</span> : null}
        {primaryDirection && typeof primaryDirection.value.description === "string" ? <p>{primaryDirection.value.description}</p> : null}
        <div className="unified-profile-hero__meta">
          <span><CheckCircle2 size={15} />{cardCount} 条已确认资料</span>
          <span>{profile.projects.length} 个代表项目</span>
          <span>{profile.skills.length} 项技能</span>
        </div>
      </div>
      <div className="unified-profile-hero__actions">
        <Button onClick={onCreateJobTarget}><Target size={16} />创建求职目标</Button>
        <Button variant="secondary" onClick={onOpenReview}><BookOpenCheck size={16} />进入自主复习</Button>
        <button type="button" onClick={() => primaryDirection ? onEdit(primaryDirection) : onCreate("direction")}><Pencil size={15} />{primaryDirection ? "编辑定位" : "设置职业定位"}</button>
      </div>
    </section>

    <details className="unified-profile-data-health">
      <summary>
        <span><CheckCircle2 size={17} />资料质量</span>
        <small>{attentionCount ? `${attentionCount} 项需要处理` : "当前资料状态正常"}</small>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div>
        {profile.pendingCount ? <button type="button" onClick={onOpenPending}>{profile.pendingCount} 条画像建议等待确认<ArrowRight size={14} /></button> : <span><CheckCircle2 size={15} />没有待确认的画像建议</span>}
        {relatedCount ? <button type="button" className="unified-profile-hero__related" onClick={() => onOpenSupportReview("related")}><AlertTriangle size={15} />{relatedCount} 条相关内容待核对<ArrowRight size={14} /></button> : null}
        {unsupportedCount ? <button type="button" className="unified-profile-hero__unsupported" onClick={() => onOpenSupportReview("unsupported")}><AlertTriangle size={15} />{unsupportedCount} 条内容缺少直接依据<ArrowRight size={14} /></button> : null}
        {!attentionCount ? <span><CheckCircle2 size={15} />已确认资料目前不需要额外处理</span> : null}
      </div>
    </details>

    <nav className="unified-profile-view-nav" aria-label="画像内容分类">
      {views.map((view) => <button
        key={view.key}
        type="button"
        aria-current={activeView === view.key ? "page" : undefined}
        onClick={() => setActiveView(view.key)}
      >
        <span>{view.label}</span>
        <small>{view.count}</small>
      </button>)}
    </nav>

    <div className="unified-profile-main">
        {activeView === "overview" ? <>
          <div className="unified-profile-overview-grid">
            <section className="unified-profile-directions">
              <header><div><Target size={18} /><h2>求职方向</h2></div><button type="button" onClick={() => onCreate("direction")}><Plus size={15} />添加</button></header>
              {profile.directions.length ? profile.directions.map((card) => <article key={card.claimId} data-primary={card.claimId === profile.primaryDirectionClaimId || undefined} data-support={card.supportStatus !== "supported" && card.supportStatus !== "manual" ? card.supportStatus : undefined}>
                <button type="button" className="unified-profile-directions__body" onClick={() => onEdit(card)}><strong>{card.title}</strong>{supportLabel(card) ? <small>{supportLabel(card)}</small> : null}{typeof card.value.description === "string" ? <span>{card.value.description}</span> : null}</button>
                {card.claimId === profile.primaryDirectionClaimId ? <small>当前方向</small> : <button type="button" onClick={() => onSetPrimaryDirection(card.claimId)}>设为当前方向</button>}
              </article>) : <button className="unified-profile-directions__empty" type="button" onClick={() => onCreate("direction")}><Plus size={16} />设置职业定位</button>}
            </section>

            <section className="unified-profile-skills">
              <header><div><BriefcaseBusiness size={18} /><h2>核心技能</h2></div><button type="button" onClick={() => onCreate("skill")}><Plus size={15} />添加</button></header>
              {profile.skills.length ? skillsExpanded ? <div className="unified-profile-skills__tags">
                {profile.skills.map((card) => <button key={card.claimId} type="button" data-support={card.supportStatus !== "supported" && card.supportStatus !== "manual" ? card.supportStatus : undefined} aria-label={`${card.title}${supportLabel(card) ? `，${supportLabel(card)}` : ""}`} onClick={() => onEdit(card)}>{card.title}{supportLabel(card) ? <small>{supportLabel(card)}</small> : null}</button>)}
                <button className="unified-profile-skills__more" type="button" onClick={() => setSkillsExpanded(false)}>收起</button>
              </div> : <div className="unified-profile-skills__summary">
                <div>{profile.skills.slice(0, 4).map((card) => <button key={card.claimId} type="button" data-support={card.supportStatus !== "supported" && card.supportStatus !== "manual" ? card.supportStatus : undefined} aria-label={`${card.title}${supportLabel(card) ? `，${supportLabel(card)}` : ""}`} onClick={() => onEdit(card)}>{card.title}{supportLabel(card) ? <small>{supportLabel(card)}</small> : null}</button>)}</div>
                <button type="button" onClick={() => setSkillsExpanded(true)}>查看全部 {profile.skills.length} 项</button>
              </div> : <button className="unified-profile-skills__empty" type="button" onClick={() => onCreate("skill")}>添加掌握的技能</button>}
            </section>

            {profile.actionableGaps.length ? <ProfileActionableGaps gaps={profile.actionableGaps} onEdit={(claimId) => {
              const cards = [...profile.projects, ...profile.experiences];
              const card = cards.find((item) => item.claimId === claimId);
              if (card) onEdit(card);
            }} /> : null}
          </div>

          {profile.highlights.length ? <section className="unified-profile-highlights" aria-labelledby="profile-highlights-title">
            <header><div><Sparkles size={18} /><h2 id="profile-highlights-title">我的亮点</h2></div><button type="button" onClick={() => onCreate("highlight")}><Plus size={15} />添加</button></header>
            <div>{profile.highlights.map((card) => <button key={card.claimId} type="button" data-support={card.supportStatus !== "supported" && card.supportStatus !== "manual" ? card.supportStatus : undefined} onClick={() => onEdit(card)}><span>{card.title}{supportLabel(card) ? <small>{supportLabel(card)}</small> : null}</span><Pencil size={14} /></button>)}</div>
          </section> : null}
          {profile.experiences.length ? <ProfileSection category="experience" cards={profile.experiences.slice(0, 1)} onCreate={onCreate} onEdit={onEdit} onShowAll={profile.experiences.length > 1 ? () => setActiveView("experience") : undefined} /> : null}
          {profile.projects.length ? <ProfileSection category="project" cards={profile.projects.slice(0, 1)} onCreate={onCreate} onEdit={onEdit} onShowAll={profile.projects.length > 1 ? () => setActiveView("project") : undefined} /> : null}
        </> : null}

        {activeView === "experience" ? <ProfileSection category="experience" cards={profile.experiences} onCreate={onCreate} onEdit={onEdit} /> : null}
        {activeView === "project" ? <ProfileSection category="project" cards={profile.projects} onCreate={onCreate} onEdit={onEdit} /> : null}
        {activeView === "education" ? <ProfileSection category="education" cards={profile.education} onCreate={onCreate} onEdit={onEdit} /> : null}
        {activeView === "achievement" ? profile.certifications.length && profile.achievements.length ? <div className="unified-profile-pair">
          <ProfileSection category="certification" cards={profile.certifications} onCreate={onCreate} onEdit={onEdit} createLabel="添加证书" />
          <ProfileSection category="achievement" cards={profile.achievements} onCreate={onCreate} onEdit={onEdit} createLabel="添加成果" />
        </div> : profile.certifications.length ? <ProfileSection category="certification" cards={profile.certifications} onCreate={onCreate} onEdit={onEdit} createLabel="添加证书" optionalCreate={{ category: "achievement", label: "添加成果" }} />
          : <ProfileSection category="achievement" cards={profile.achievements} onCreate={onCreate} onEdit={onEdit} createLabel="添加成果" optionalCreate={{ category: "certification", label: "添加证书（可选）" }} /> : null}
    </div>
  </main>;
}
