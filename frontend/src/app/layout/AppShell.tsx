import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Badge } from "../../shared/ui/Badge";
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { ReviewPage } from "../../features/review/ReviewPage";
import type { ReviewQuestion } from "../../features/review/reviewTypes";
import { SettingsPage } from "../../features/settings/SettingsPage";
import type { WorkspaceConfig } from "../../features/settings/settingsApi";

type StepState = "pending" | "active" | "done";

export function AppShell() {
  const [workspace, setWorkspace] = useState<WorkspaceConfig | null>(null);
  const [draftQuestion, setDraftQuestion] = useState<ReviewQuestion | null>(null);
  const [latestReportMarkdown, setLatestReportMarkdown] = useState("");

  const step1: StepState = workspace ? "done" : "active";
  const step2: StepState = draftQuestion ? "done" : workspace ? "active" : "pending";
  const step3: StepState = latestReportMarkdown
    ? "done"
    : draftQuestion
      ? "active"
      : "pending";

  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <div className="app-header__brand">
            <span className="app-header__logo" aria-hidden="true">
              <ShieldCheck size={22} />
            </span>
            <div>
              <h1 className="app-header__title">Cyber Interview Agent</h1>
              <p className="app-header__subtitle">复习闭环 MVP</p>
            </div>
          </div>
          <div className="app-header__status">
            {workspace ? (
              <Badge tone="success" dot>
                工作区就绪
              </Badge>
            ) : (
              <Badge tone="neutral" dot>
                未初始化
              </Badge>
            )}
          </div>
        </div>
      </header>

      <nav className="progress-strip" aria-label="工作流进度">
        <ol className="progress-strip__steps">
          <li className="progress-strip__step" data-state={step1}>
            设置
          </li>
          <li className="progress-strip__divider" aria-hidden="true" />
          <li className="progress-strip__step" data-state={step2}>
            知识
          </li>
          <li className="progress-strip__divider" aria-hidden="true" />
          <li className="progress-strip__step" data-state={step3}>
            复习
          </li>
        </ol>
      </nav>

      <main className="app-main">
        <div className="app-container">
          <SettingsPage workspace={workspace} onWorkspaceReady={setWorkspace} />
          <KnowledgePage workspace={workspace} draftQuestion={draftQuestion} onDraftQuestionReady={setDraftQuestion} />
          <ReviewPage
            workspace={workspace}
            draftQuestion={draftQuestion}
            latestReportMarkdown={latestReportMarkdown}
            onReportMarkdownChange={setLatestReportMarkdown}
          />
        </div>
      </main>
    </>
  );
}
