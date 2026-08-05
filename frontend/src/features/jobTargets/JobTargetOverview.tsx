import { BookOpenCheck, CheckCircle2, CircleAlert, FileText, FolderKanban, ListChecks, MessageSquareText, UserRound } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { JobAnalysisStatus } from "./JobAnalysisStatus";
import type { JobAnalysis, JobTarget, JobTargetRetrospectiveSummary, TargetReadiness } from "./jobTargetTypes";

const labels: Record<string, string> = {
  requirements_pending: "先确认岗位要求",
  project_selection_pending: "选择重点准备项目",
  deep_dive_in_progress: "继续项目深挖",
  high_risk_open: "处理尚未掌握的项目问题",
  core_preparation_complete: "核心准备已完成",
};

interface JobTargetOverviewProps {
  target: JobTarget;
  readiness?: TargetReadiness;
  analysis?: JobAnalysis | null;
  retrospectiveSummary?: JobTargetRetrospectiveSummary;
  profileSummary?: { confirmedItems: number; projectCount: number };
  onEditJd: () => void;
  onCompleteInfo: () => void;
  onStartAnalysis: () => void;
  onControl: (action: "pause" | "resume" | "terminate") => void;
  onNavigate: (tab: "requirements" | "deep-dive" | "review") => void;
  onStartTargetReview: () => void;
  onOpenRetrospectives: () => void;
}

export function JobTargetOverview({
  target,
  readiness,
  analysis,
  retrospectiveSummary,
  profileSummary,
  onEditJd,
  onCompleteInfo,
  onStartAnalysis,
  onControl,
  onNavigate,
  onStartTargetReview,
  onOpenRetrospectives,
}: JobTargetOverviewProps) {
  const targetIncomplete = !target.roleName.trim() || !target.seniority.trim();
  const nextTab = readiness?.status === "requirements_pending"
    ? "requirements"
    : readiness?.status === "project_selection_pending" || readiness?.status === "deep_dive_in_progress"
      ? "deep-dive"
      : "review";
  const nextTitle = !target.currentDocumentVersionId
    ? "先添加岗位描述"
    : targetIncomplete
      ? "先补全岗位信息"
      : labels[readiness?.status ?? "requirements_pending"];
  const confirmedQuestions = readiness?.confirmedProjectQuestions ?? 0;
  const requirementsReady = (readiness?.pendingRequirements ?? 0) === 0 && (readiness?.confirmedRequirements ?? 0) > 0;
  const projectReady = Boolean(readiness?.coreProjectId);
  const gaps = Object.entries(retrospectiveSummary?.gapCounts ?? {}).sort((left, right) => right[1] - left[1]);

  return <div className="job-target-overview">
    <section className="job-target-overview__lead">
      <div>
        <span>当前最重要的一步</span>
        <h2>{nextTitle}</h2>
        <p>岗位要求决定准备方向，个人画像提供真实经历，项目深挖和专项复习负责把经历练成能回答的问题。</p>
      </div>
      <div className="job-target-overview__lead-actions">
        {target.currentDocumentVersionId ? <Button variant="secondary" onClick={onStartAnalysis} title="重新读取当前 JD；已确认和已忽略的决定不会自动改变">重新分析</Button> : null}
        {!target.currentDocumentVersionId
          ? <Button onClick={onEditJd}><FileText size={16} />添加岗位描述</Button>
          : targetIncomplete
            ? <Button onClick={onCompleteInfo}>补全岗位信息</Button>
            : <Button onClick={() => onNavigate(nextTab)}>继续准备</Button>}
      </div>
    </section>

    {analysis ? <JobAnalysisStatus analysis={analysis} onControl={onControl} onOpenRequirements={() => onNavigate("requirements")} onOpenProjects={() => onNavigate("deep-dive")} /> : null}

    <section className="job-target-overview__summary" aria-label="岗位准备概览">
      <article>
        <UserRound />
        <div><strong>个人画像</strong><p>{profileSummary ? `${profileSummary.confirmedItems} 条画像资料 · ${profileSummary.projectCount} 个项目` : "正在读取个人画像"}</p></div>
      </article>
      <article>
        <ListChecks />
        <div><strong>岗位要求</strong><p><span>{readiness?.confirmedRequirements ?? 0} 条已确认</span><span>{readiness?.pendingRequirements ?? 0} 条待确认</span>{readiness?.rejectedRequirements ? <span>{readiness.rejectedRequirements} 条已忽略</span> : null}</p></div>
      </article>
      <article>
        <FolderKanban />
        <div><strong>重点项目</strong><p>{readiness?.coreProjectId ? `已选核心项目${readiness.supplementaryProjectIds.length ? `和 ${readiness.supplementaryProjectIds.length} 个补充项目` : ""}` : "尚未选择核心项目"}</p></div>
      </article>
      <article>
        <BookOpenCheck />
        <div><strong>可复习项目题</strong><p>{confirmedQuestions ? `${confirmedQuestions} 道已确认项目题` : "还没有已确认的项目题"}</p></div>
      </article>
    </section>

    <section className="job-target-overview__journey" aria-labelledby="job-target-journey-title">
      <header>
        <div>
          <span>准备路径</span>
          <h3 id="job-target-journey-title">把岗位信息变成可以反复练习的题目</h3>
        </div>
        <p>前面的准备会直接决定专项复习的内容。</p>
      </header>
      <ol className="job-target-overview__steps">
        <li data-state={requirementsReady ? "complete" : "current"}>
          <button className="job-target-overview__step" type="button" onClick={() => onNavigate("requirements")}>
            <span className="job-target-overview__step-marker">1</span>
            <div><span>{requirementsReady ? "已完成" : "当前建议"}</span><strong>确认岗位要求</strong><p>{readiness?.pendingRequirements ? `${readiness.pendingRequirements} 条等待确认` : `${readiness?.confirmedRequirements ?? 0} 条已确认`}</p></div>
            <ListChecks />
          </button>
        </li>
        <li data-state={projectReady ? "complete" : requirementsReady ? "current" : "pending"}>
          <button className="job-target-overview__step" type="button" onClick={() => onNavigate("deep-dive")}>
            <span className="job-target-overview__step-marker">2</span>
            <div><span>{projectReady ? "已选择" : requirementsReady ? "下一步" : "待完成"}</span><strong>深挖重点项目</strong><p>{projectReady ? "继续完善项目讲解和风险" : "先选择一个核心项目"}</p></div>
            <FolderKanban />
          </button>
        </li>
        <li data-state={confirmedQuestions ? "complete" : projectReady ? "current" : "pending"}>
          <button className="job-target-overview__step" type="button" onClick={() => onNavigate("review")}>
            <span className="job-target-overview__step-marker">3</span>
            <div><span>{confirmedQuestions ? "已有题目" : projectReady ? "下一步" : "待完成"}</span><strong>确认项目题</strong><p>{confirmedQuestions ? `${confirmedQuestions} 道已进入题库` : "确认候选题后解锁专项复习"}</p></div>
            {confirmedQuestions ? <CheckCircle2 /> : <CircleAlert />}
          </button>
        </li>
        <li data-state={confirmedQuestions ? "current" : "locked"}>
          <button
            aria-label="开始岗位专项复习"
            className="job-target-overview__step"
            type="button"
            disabled={!confirmedQuestions}
            onClick={onStartTargetReview}
          >
            <span className="job-target-overview__step-marker">4</span>
            <div><span>{confirmedQuestions ? "可以开始" : "尚未解锁"}</span><strong>岗位专项复习</strong><p>{confirmedQuestions ? `只练本目标下的 ${confirmedQuestions} 道项目题` : "确认项目题后即可开始岗位专项复习"}</p></div>
            <BookOpenCheck />
          </button>
        </li>
      </ol>
    </section>

    <section className="job-target-overview__retrospectives" aria-label="面试反馈">
      <header>
        <div><MessageSquareText size={18} /><span>面试反馈</span></div>
        <Button size="sm" variant="secondary" onClick={onOpenRetrospectives}>{retrospectiveSummary?.retrospectiveCount ? "查看全部复盘" : "开始第一次复盘"}</Button>
      </header>
      {retrospectiveSummary?.retrospectiveCount ? <>
        <div className="job-target-overview__retrospective-metrics">
          <div><strong>{retrospectiveSummary.retrospectiveCount}</strong><span>场复盘</span></div>
          <div><strong>{retrospectiveSummary.latest?.roundLabel ?? "—"}</strong><span>最近一轮 · {retrospectiveSummary.latest?.outcome === "passed" ? "通过" : retrospectiveSummary.latest?.outcome === "failed" ? "未通过" : "结果待记录"}</span></div>
          <div><strong>{retrospectiveSummary.unresolvedActionCount}</strong><span>项还要准备</span></div>
        </div>
        {gaps.length ? <p>反复出现的短板：{gaps.slice(0, 3).map(([kind, count]) => `${gapLabel(kind)} ${count}`).join(" · ")}</p> : <p>目前没有未解决的能力短板。</p>}
      </> : <div className="job-target-overview__retrospective-empty"><strong>还没有面试反馈</strong><p>面试后粘贴转写或回忆，逐轮积累这个岗位的真实反馈。</p></div>}
    </section>
  </div>;
}

function gapLabel(kind: string) {
  return ({ material: "素材", expression: "表达", knowledge: "知识", experience: "经历" } as Record<string, string>)[kind] ?? kind;
}
