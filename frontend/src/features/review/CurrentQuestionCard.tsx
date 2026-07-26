import { BookOpen, Eye, FileSearch, Lightbulb, SkipForward } from "lucide-react";
import { useState } from "react";
import { Button } from "../../shared/ui/Button";
import type { ReviewRound } from "./reviewTypes";

type CurrentQuestion = NonNullable<ReviewRound["currentQuestion"]>;

export function CurrentQuestionCard({
  question,
  busy = false,
  onHint,
  onReveal,
  onSkip,
}: {
  question: CurrentQuestion;
  busy?: boolean;
  onHint: () => void;
  onReveal: () => void;
  onSkip: () => void;
}) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const requiredCount = question.requiredKeyPointCount ?? 0;
  const coveredCount = question.coveredKeyPointCount ?? 0;
  const missingDirections = question.missingDirections ?? [];
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
        {question.hasAnswer && missingDirections.length > 0
          ? <ul>{missingDirections.map((item) => <li key={item}>{item}</li>)}</ul>
          : <small>{question.hasAnswer ? "已覆盖全部必答方向" : "回答后会逐步显示仍需补充的方向"}</small>}
      </div>
      <footer>
        <div className="current-question-card__help">
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onHint}><Lightbulb size={15} />查看提示</Button>
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onReveal}><Eye size={15} />查看答案</Button>
          <Button type="button" size="sm" variant="ghost" aria-expanded={sourceOpen} onClick={() => setSourceOpen((value) => !value)}><FileSearch size={15} />查看来源</Button>
        </div>
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onSkip}><SkipForward size={15} />跳过此题</Button>
      </footer>
      {sourceOpen ? <div className="current-question-card__source"><span>冻结来源</span><strong>{question.documentId ?? "来源信息暂不可用"}</strong></div> : null}
    </section>
  );
}
