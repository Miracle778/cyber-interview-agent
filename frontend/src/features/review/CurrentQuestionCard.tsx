import { BookOpen, Eye, FileSearch, FileText, Lightbulb, SkipForward } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound } from "./reviewTypes";

type CurrentQuestion = NonNullable<ReviewRound["currentQuestion"]>;

function formatSectionNumbers(values: number[]) {
  const sorted = [...new Set(values)].sort((left, right) => left - right);
  const ranges: string[] = [];
  for (let index = 0; index < sorted.length; index += 1) {
    const start = sorted[index];
    let end = start;
    while (index + 1 < sorted.length && sorted[index + 1] === end + 1) {
      end = sorted[index + 1];
      index += 1;
    }
    ranges.push(start === end ? `${start}` : `${start}–${end}`);
  }
  return ranges.join("、");
}

export function CurrentQuestionCard({
  question,
  busy = false,
  referenceShown = false,
  onHint,
  onReveal,
  onSkip,
}: {
  question: CurrentQuestion;
  busy?: boolean;
  referenceShown?: boolean;
  onHint: () => void;
  onReveal: () => void;
  onSkip: () => void;
}) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const requiredCount = question.requiredKeyPointCount ?? 0;
  const coveredCount = question.coveredKeyPointCount ?? 0;
  const missingDirections = question.missingDirections ?? [];
  const sources = question.sources ?? [];
  return (
    <section className="current-question-card" aria-label="当前题目">
      <header>
        <div>
          <span><BookOpen size={15} />当前题目</span>
          <h3>{question.title}</h3>
        </div>
        <div className="current-question-card__topics">
          {question.topics.map((topic) => <span key={topic}>{topic}</span>)}
        </div>
      </header>
      <p className="current-question-card__prompt">{question.questionText}</p>
      <div className="current-question-card__progress">
        <strong>
          {question.hasAnswer
            ? `已覆盖 ${coveredCount} / ${requiredCount}`
            : `${requiredCount} 个必答方向`}
        </strong>
        <small>
          {question.hasAnswer
            ? missingDirections.length > 0
              ? `还有 ${missingDirections.length} 个方向待完善，详情见右侧`
              : "已覆盖全部必答方向"
            : "回答后在右侧显示待完善方向"}
        </small>
      </div>
      <footer>
        <div className="current-question-card__help">
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onHint}><Lightbulb size={15} />查看提示</Button>
          {referenceShown
            ? <Button type="button" size="sm" variant="ghost" disabled><Eye size={15} />参考答案已展示</Button>
            : <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onReveal}><Eye size={15} />查看答案</Button>}
          <Button type="button" size="sm" variant="ghost" aria-expanded={sourceOpen} onClick={() => setSourceOpen((value) => !value)}><FileSearch size={15} />查看来源</Button>
        </div>
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onSkip}><SkipForward size={15} />跳过此题</Button>
      </footer>
      {sourceOpen ? <section className="current-question-card__source" aria-label="题目来源">
        <header><FileText size={15} /><strong>题目来源</strong><span>{sources.length ? `${sources.length} 份文档` : "暂无可查看文档"}</span></header>
        {sources.length ? <ul>{sources.map((source) => {
          const location = source.sectionNumbers.length
            ? `原文片段 ${formatSectionNumbers(source.sectionNumbers)}`
            : source.evidenceCount > 1
              ? `关联 ${source.evidenceCount} 处原文`
              : "已关联原文依据";
          return <li key={source.sourceId}>
            <div><strong>{source.filename ?? "来源文档信息暂不可用"}</strong><small>{location}</small></div>
            {source.availability === "deleted" ? <span>原资料已移入回收站</span> : source.availability === "missing" ? <span>原资料已不可用</span> : null}
          </li>;
        })}</ul> : <p>这道题暂未关联可查看的来源文档。</p>}
      </section> : null}
    </section>
  );
}
