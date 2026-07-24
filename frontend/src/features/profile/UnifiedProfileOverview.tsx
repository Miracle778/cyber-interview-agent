import { ArrowRight, BriefcaseBusiness, CheckCircle2, FileUp, Pencil, Plus, Sparkles, Target, UserRound } from "lucide-react";
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

function ProfileCard({ card, onEdit }: { card: UnifiedProfileCard; onEdit: (card: UnifiedProfileCard) => void }) {
  const details = cardDetails(card);
  const technologies = card.category === "project" ? textList(card.value.tech_stack) : [];
  return <article className="unified-profile-card">
    <header>
      <div><h3>{card.title}</h3>{card.subtitle ? <p>{card.subtitle}</p> : null}</div>
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

function ProfileSection({ category, cards, onCreate, onEdit }: { category: ProfileCardCategory; cards: UnifiedProfileCard[]; onCreate: (category: ProfileCardCategory) => void; onEdit: (card: UnifiedProfileCard) => void }) {
  return <section className="unified-profile-section" aria-labelledby={`profile-${category}-title`}>
    <header>
      <div><h2 id={`profile-${category}-title`}>{sectionLabels[category] ?? category}</h2><span>{cards.length} 条</span></div>
      <button type="button" onClick={() => onCreate(category)}><Plus size={16} />添加</button>
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
  onSetPrimaryDirection,
}: {
  profile: UnifiedProfile | null;
  loading: boolean;
  onUpload: () => void;
  onCreate: (category?: ProfileCardCategory) => void;
  onEdit: (card: UnifiedProfileCard) => void;
  onOpenPending: () => void;
  onSetPrimaryDirection: (claimId: string) => void;
}) {
  if (loading) return <div className="profile-loading" role="status"><span className="profile-loading__bar" /><span className="profile-loading__bar" /><p>正在读取个人画像…</p></div>;
  if (!profile) return null;

  const cardCount = profile.experiences.length + profile.projects.length + profile.skills.length + profile.education.length + profile.certifications.length + profile.achievements.length;
  const primaryDirection = profile.directions.find((item) => item.claimId === profile.primaryDirectionClaimId) ?? profile.directions[0] ?? null;

  if (!profile.isUsable && !profile.summary && !profile.directions.length && !profile.highlights.length) {
    return <section className="unified-profile-empty">
      <span><UserRound size={30} /></span>
      <h2>从这里建立你的个人画像</h2>
      <p>画像是你确认过的经历、项目和技能，会被后续的岗位分析、简历优化和面试训练共同使用。</p>
      <div><Button onClick={onUpload}><FileUp size={17} />上传简历自动整理</Button><Button variant="secondary" onClick={() => onCreate("project")}><Pencil size={17} />从空白开始</Button></div>
      <small>两种方式可以同时使用，所有内容都能随时修改。</small>
    </section>;
  }

  return <main className="unified-profile">
    <section className="unified-profile-hero">
      <div className="unified-profile-hero__content">
        <span>我的职业名片</span>
        <h2>{profile.summary?.title ?? primaryDirection?.title ?? "补充一句话介绍，让别人更快了解你"}</h2>
        {profile.summary?.title && primaryDirection ? <p>{primaryDirection.title}{primaryDirection.value.description ? ` · ${String(primaryDirection.value.description)}` : ""}</p> : null}
        <div className="unified-profile-hero__meta">
          <span><CheckCircle2 size={15} />{cardCount} 条已确认资料</span>
          {profile.pendingCount ? <button type="button" onClick={onOpenPending}>{profile.pendingCount} 条内容等你确认<ArrowRight size={14} /></button> : <span>当前没有待确认内容</span>}
        </div>
      </div>
      <div className="unified-profile-hero__actions">
        <Button variant="secondary" onClick={() => onCreate(profile.summary ? "highlight" : "summary")}><Plus size={16} />补充资料</Button>
        {profile.summary ? <button type="button" onClick={() => onEdit(profile.summary!)}><Pencil size={15} />编辑个人简介</button> : null}
      </div>
    </section>

    <div className="unified-profile-layout">
      <div className="unified-profile-main">
        {profile.highlights.length ? <section className="unified-profile-highlights" aria-labelledby="profile-highlights-title">
          <header><div><Sparkles size={18} /><h2 id="profile-highlights-title">我的亮点</h2></div><button type="button" onClick={() => onCreate("highlight")}><Plus size={15} />添加</button></header>
          <div>{profile.highlights.map((card) => <button key={card.claimId} type="button" onClick={() => onEdit(card)}><span>{card.title}</span><Pencil size={14} /></button>)}</div>
        </section> : null}

        <ProfileSection category="experience" cards={profile.experiences} onCreate={onCreate} onEdit={onEdit} />
        <ProfileSection category="project" cards={profile.projects} onCreate={onCreate} onEdit={onEdit} />
        <ProfileSection category="education" cards={profile.education} onCreate={onCreate} onEdit={onEdit} />
        {(profile.certifications.length || profile.achievements.length) ? <div className="unified-profile-pair">
          <ProfileSection category="certification" cards={profile.certifications} onCreate={onCreate} onEdit={onEdit} />
          <ProfileSection category="achievement" cards={profile.achievements} onCreate={onCreate} onEdit={onEdit} />
        </div> : null}
      </div>

      <aside className="unified-profile-aside">
        <section className="unified-profile-directions">
          <header><div><Target size={18} /><h2>求职方向</h2></div><button type="button" onClick={() => onCreate("direction")}><Plus size={15} />添加</button></header>
          {profile.directions.length ? profile.directions.map((card) => <article key={card.claimId} data-primary={card.claimId === profile.primaryDirectionClaimId || undefined}>
            <button type="button" className="unified-profile-directions__body" onClick={() => onEdit(card)}><strong>{card.title}</strong>{typeof card.value.description === "string" ? <span>{card.value.description}</span> : null}</button>
            {card.claimId === profile.primaryDirectionClaimId ? <small>当前方向</small> : <button type="button" onClick={() => onSetPrimaryDirection(card.claimId)}>设为当前方向</button>}
          </article>) : <button className="unified-profile-directions__empty" type="button" onClick={() => onCreate("direction")}><Plus size={16} />添加求职方向</button>}
        </section>

        <section className="unified-profile-skills">
          <header><div><BriefcaseBusiness size={18} /><h2>技能</h2></div><button type="button" onClick={() => onCreate("skill")}><Plus size={15} />添加</button></header>
          {profile.skills.length ? <div>{profile.skills.map((card) => <button key={card.claimId} type="button" onClick={() => onEdit(card)}>{card.title}</button>)}</div> : <button className="unified-profile-skills__empty" type="button" onClick={() => onCreate("skill")}>添加掌握的技能</button>}
        </section>

        <ProfileActionableGaps gaps={profile.actionableGaps} onEdit={(claimId) => {
          const cards = [...profile.projects, ...profile.experiences];
          const card = cards.find((item) => item.claimId === claimId);
          if (card) onEdit(card);
        }} />
      </aside>
    </div>
  </main>;
}
