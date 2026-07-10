import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, FolderCheck, Loader2, ShieldCheck } from "lucide-react";
import { getHealth } from "../../shared/api/health";
import { Badge } from "../../shared/ui/Badge";
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { ReviewPage } from "../../features/review/ReviewPage";
import type { ReviewQuestion } from "../../features/review/reviewTypes";
import { SettingsPage } from "../../features/settings/SettingsPage";
import { getWorkspace, type WorkspaceConfig } from "../../features/settings/settingsApi";

type StepState = "pending" | "active" | "done";
type HealthState = {
  status: "checking" | "connected" | "disconnected";
  message: string;
};

export function AppShell() {
  const [health, setHealth] = useState<HealthState>({
    status: "checking",
    message: "正在检查后端连接",
  });
  const [workspace, setWorkspace] = useState<WorkspaceConfig | null>(null);
  const [draftQuestion, setDraftQuestion] = useState<ReviewQuestion | null>(null);
  const [latestReportMarkdown, setLatestReportMarkdown] = useState("");
  const [reportConfirmed, setReportConfirmed] = useState(false);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);

  useEffect(() => {
    let ignore = false;

    async function restoreWorkspace() {
      setHealth({ status: "checking", message: "正在检查后端连接" });

      try {
        await getHealth();
        if (ignore) return;

        setHealth({ status: "connected", message: "后端已连接" });
      } catch {
        if (!ignore) {
          setHealth({
            status: "disconnected",
            message: "后端未连接，请确认 FastAPI 服务已启动",
          });
        }
        return;
      }

      try {
        const savedWorkspace = await getWorkspace();
        if (!ignore && savedWorkspace) {
          setWorkspace(savedWorkspace);
        }
      } catch {
        // Workspace restore is best-effort; backend health remains connected.
      }
    }

    void restoreWorkspace();

    return () => {
      ignore = true;
    };
  }, []);

  const step1: StepState = workspace ? "done" : "active";
  const step2: StepState = draftQuestion ? "done" : workspace ? "active" : "pending";
  const step3: StepState = latestReportMarkdown
    ? "done"
    : draftQuestion
      ? "active"
      : "pending";
  const backendConnectionText =
    health.status === "connected"
      ? "后端连接：已连接"
      : health.status === "disconnected"
        ? "后端连接：未连接"
        : "后端连接：检查中";
  const workspaceStatusText = workspace ? "Workspace：已初始化" : "Workspace：待初始化";
  const draftStatusText = draftQuestion ? "题库草稿：已生成" : "题库草稿：待生成";
  const reportStatusText = reportConfirmed
    ? "复习报告：已确认"
    : latestReportMarkdown
      ? "复习报告：待确认"
      : "复习报告：待生成";
  const vaultStatusText =
    indexedCount === null ? "Vault 索引：待扫描" : `Vault 索引：已扫描 ${indexedCount} 个文档`;
  const nextStepText = getNextStepText({
    healthStatus: health.status,
    workspace,
    draftQuestion,
    latestReportMarkdown,
    reportConfirmed,
    indexedCount,
  });

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
          <div className="status-strip">
            <p className="app-health" data-state={health.status}>
              <span className="app-health__icon" aria-hidden="true">
                {health.status === "connected" ? (
                  <CheckCircle2 size={15} />
                ) : health.status === "disconnected" ? (
                  <AlertTriangle size={15} />
                ) : (
                  <Loader2 size={15} className="app-health__spin" />
                )}
              </span>
              {health.message}
            </p>
            {workspace ? (
              <p className="app-health" data-state="workspace">
                <span className="app-health__icon" aria-hidden="true">
                  <FolderCheck size={15} />
                </span>
                Workspace：{workspace.workspacePath}
              </p>
            ) : null}
          </div>
          <section className="flow-status" aria-label="流程状态">
            <p className="flow-status__label">流程状态</p>
            <div className="flow-status__grid">
              <p data-state={health.status === "connected" ? "done" : health.status === "disconnected" ? "error" : "active"}>
                {backendConnectionText}
              </p>
              <p data-state={workspace ? "done" : "pending"}>{workspaceStatusText}</p>
              <p data-state={draftQuestion ? "done" : "pending"}>{draftStatusText}</p>
              <p data-state={reportConfirmed ? "done" : latestReportMarkdown ? "active" : "pending"}>{reportStatusText}</p>
              <p data-state={indexedCount === null ? "pending" : "done"}>{vaultStatusText}</p>
            </div>
            <p className="flow-status__next">
              <ArrowRight size={15} aria-hidden="true" />
              {nextStepText}
            </p>
          </section>
          <SettingsPage
            workspace={workspace}
            onWorkspaceReady={(readyWorkspace) => {
              setWorkspace(readyWorkspace);
              setDraftQuestion(null);
              setLatestReportMarkdown("");
              setReportConfirmed(false);
              setIndexedCount(null);
            }}
          />
          <KnowledgePage
            workspace={workspace}
            draftQuestion={draftQuestion}
            onDraftQuestionReady={(question) => {
              setDraftQuestion(question);
              setLatestReportMarkdown("");
              setReportConfirmed(false);
            }}
            onVaultRescanned={setIndexedCount}
          />
          <ReviewPage
            workspace={workspace}
            draftQuestion={draftQuestion}
            latestReportMarkdown={latestReportMarkdown}
            onReportMarkdownChange={(markdown) => {
              setLatestReportMarkdown(markdown);
              setReportConfirmed(false);
            }}
            onReportConfirmed={() => setReportConfirmed(true)}
          />
        </div>
      </main>
    </>
  );
}

interface NextStepState {
  healthStatus: HealthState["status"];
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  reportConfirmed: boolean;
  indexedCount: number | null;
}

function getNextStepText({
  healthStatus,
  workspace,
  draftQuestion,
  latestReportMarkdown,
  reportConfirmed,
  indexedCount,
}: NextStepState) {
  if (healthStatus === "disconnected") return "下一步：启动后端服务";
  if (!workspace) return "下一步：初始化工作区";
  if (!draftQuestion) return "下一步：上传资料生成题库草稿";
  if (!latestReportMarkdown) return "下一步：发送回答生成复习报告";
  if (!reportConfirmed) return "下一步：确认报告";
  if (indexedCount === null) return "下一步：重新扫描 Vault";
  return "下一步：继续下一轮复习";
}
