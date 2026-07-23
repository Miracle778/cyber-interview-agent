import { useEffect, useState, type ReactNode } from "react";
import { Sparkles } from "lucide-react";
import { Navigate, Route, Routes } from "react-router-dom";
import { getHealth } from "../../shared/api/health";
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { ReviewPage } from "../../features/review/ReviewPage";
import type { ReviewQuestion } from "../../features/review/reviewTypes";
import { ProfilePage } from "../../features/profile/ProfilePage";
import { SettingsPage } from "../../features/settings/SettingsPage";
import { getWorkspace, type WorkspaceConfig } from "../../features/settings/settingsApi";
import { MobileNavigation } from "../navigation/MobileNavigation";
import { PrimaryNavigation } from "../navigation/PrimaryNavigation";
import { PageHeader } from "./PageHeader";

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

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      <aside className="desktop-sidebar">
        <div className="desktop-sidebar__brand">
          <span className="desktop-sidebar__mark" aria-hidden="true">
            <Sparkles size={20} />
          </span>
          <div>
            <p className="desktop-sidebar__name">Cyber Interview</p>
            <p className="desktop-sidebar__kind">个人面试工作台</p>
          </div>
        </div>
        <PrimaryNavigation />
        <div className="desktop-sidebar__footer">
          <span className="status-dot" data-state={health.status} aria-hidden="true" />
          <span>{health.status === "connected" ? "本地服务已连接" : health.status === "checking" ? "正在连接本地服务" : "本地服务未连接"}</span>
        </div>
      </aside>
      <MobileNavigation />
      <main id="main-content" className="app-main" tabIndex={-1}>
        <div className="app-container">
          <Routes>
            <Route path="/" element={<Navigate to="/review" replace />} />
            <Route
              path="/review"
              element={
                <PageFrame
                  title="复习"
                  description="围绕题库持续练习，形成可追踪的掌握度。"
                  health={health}
                  workspace={workspace}
                  workspaceMode={Boolean(workspace)}
                >
                  <ReviewPage workspace={workspace} draftQuestion={draftQuestion} />
                </PageFrame>
              }
            />
            <Route
              path="/knowledge"
              element={
                <PageFrame
                  title="知识库"
                  description="管理 Agent 可引用的资料、草稿与 Vault 索引。"
                  health={health}
                  workspace={workspace}
                >
                  <KnowledgePage
                    workspace={workspace}
                    draftQuestion={draftQuestion}
                    onDraftQuestionReady={(question) => {
                      setDraftQuestion(question);
                    }}
                    onVaultRescanned={setIndexedCount}
                  />
                </PageFrame>
              }
            />
            <Route
              path="/profile"
              element={
                <PageFrame
                  title="个人资料"
                  description="管理简历版本、可追溯证据和个人画像。"
                  health={health}
                  workspace={workspace}
                  workspaceMode
                >
                  <ProfilePage workspace={workspace} />
                </PageFrame>
              }
            />
            <Route
              path="/settings"
              element={
                <PageFrame
                  title="设置"
                  description="配置工作区、模型服务与不同任务的模型用途。"
                  health={health}
                  workspace={workspace}
                >
                  <SettingsPage
                    workspace={workspace}
                    onWorkspaceReady={(readyWorkspace) => {
                      setWorkspace(readyWorkspace);
                      setDraftQuestion(null);
                      setIndexedCount(null);
                    }}
                  />
                </PageFrame>
              }
            />
            <Route path="*" element={<Navigate to="/review" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

interface PageFrameProps {
  title: string;
  description: string;
  health: HealthState;
  workspace: WorkspaceConfig | null;
  children: ReactNode;
  workspaceMode?: boolean;
}

function PageFrame({ title, description, health, workspace, children, workspaceMode = false }: PageFrameProps) {
  return (
    <div className={workspaceMode ? "page-shell page-shell--workspace" : "page-shell"}>
      {workspaceMode ? null : <PageHeader
          title={title}
          description={description}
          healthStatus={health.status}
          healthMessage={health.message}
          workspace={workspace}
        />}
      <div className="page-content">{children}</div>
    </div>
  );
}
