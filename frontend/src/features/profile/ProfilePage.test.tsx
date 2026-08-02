import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ProfilePage } from "./ProfilePage";

const api = vi.hoisted(() => ({
  listProfileMaterials: vi.fn(),
  listMaterialVersions: vi.fn(),
  getMaterialVersion: vi.fn(),
  uploadProfileMaterial: vi.fn(),
  addMaterialVersion: vi.fn(),
  retryMaterialVersion: vi.fn(),
  archiveMaterial: vi.fn(),
  restoreMaterial: vi.fn(),
  setPrimaryVersion: vi.fn(),
  listProfileClaims: vi.fn(),
  listProfileSessions: vi.fn(),
  getUnifiedProfile: vi.fn(),
  createProfileCard: vi.fn(),
  updateProfileCard: vi.fn(),
  deleteProfileCard: vi.fn(),
  updateProfilePresentation: vi.fn(),
}));

vi.mock("./profileApi", () => api);

function renderPage(workspace = { id: "w1", workspacePath: "/workspace", vaultPath: "/vault" }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<MemoryRouter><QueryClientProvider client={client}><ProfilePage workspace={workspace} /></QueryClientProvider></MemoryRouter>);
  return {
    ...view,
    rerenderWorkspace(nextWorkspace: typeof workspace) {
      view.rerender(<MemoryRouter><QueryClientProvider client={client}><ProfilePage workspace={nextWorkspace} /></QueryClientProvider></MemoryRouter>);
    },
  };
}

describe("ProfilePage", () => {
  const emptyProfile = {
    workspaceId: "w1", profileVersion: null, summary: null, directions: [],
    primaryDirectionClaimId: null, presentationVersion: 0, highlights: [],
    experiences: [], projects: [], skills: [], education: [], certifications: [],
    achievements: [], links: [], actionableGaps: [], pendingCount: 0, isUsable: false,
  };

  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    api.listProfileMaterials.mockResolvedValue([]);
    api.listMaterialVersions.mockResolvedValue([]);
    api.listProfileClaims.mockResolvedValue({ workspaceId: "w1", profileVersion: null, claims: [], proposals: [] });
    api.listProfileSessions.mockResolvedValue([]);
    api.getUnifiedProfile.mockResolvedValue(emptyProfile);
    api.createProfileCard.mockResolvedValue({ claimId: "p1", claimVersionId: "pv1", category: "project", version: 1, status: "confirmed" });
  });

  it("supports starting without a resume and validates files in the source screen", async () => {
    let resolveProfile!: (value: typeof emptyProfile) => void;
    api.getUnifiedProfile.mockReturnValueOnce(new Promise((resolve) => { resolveProfile = resolve; }));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取个人画像");
    resolveProfile(emptyProfile);
    expect(await screen.findByText("从这里建立你的个人画像")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /从空白开始/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "简历与来源" }));
    expect(await screen.findByText("还没有简历")).toBeInTheDocument();

    const picker = screen.getByLabelText("选择简历文件");
    fireEvent.change(picker, { target: { files: [new File(["x"], "resume.exe")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("支持 PDF、DOCX、Markdown 或 TXT");

    const tooLarge = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "resume.pdf", { type: "application/pdf" });
    fireEvent.drop(screen.getByTestId("profile-dropzone"), { dataTransfer: { files: [tooLarge] } });
    expect(screen.getByRole("alert")).toHaveTextContent("不能超过 10 MB");
    expect(api.uploadProfileMaterial).not.toHaveBeenCalled();
  });

  it("creates the first profile card without requiring a resume", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /从空白开始/ }));
    fireEvent.change(screen.getByLabelText(/项目名称/), { target: { value: "面试训练平台" } });
    fireEvent.change(screen.getByLabelText(/你的角色/), { target: { value: "后端开发" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.createProfileCard).toHaveBeenCalledWith(expect.objectContaining({
      workspaceId: "w1",
      category: "project",
      expectedVersion: 0,
      value: expect.objectContaining({ name: "面试训练平台", role: "后端开发" }),
    })));
  });

  it("uploads a valid resume and gives an actionable retry when loading fails", async () => {
    api.listProfileMaterials.mockRejectedValueOnce(new Error("offline"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("个人资料读取失败");
    api.listProfileMaterials.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    await waitFor(() => expect(api.listProfileMaterials).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "简历与来源" }));
    expect(await screen.findByText("还没有简历")).toBeInTheDocument();

    api.uploadProfileMaterial.mockResolvedValue({ materialId: "m1", versionId: "v1", executionId: "e1", processingStatus: "uploaded" });
    fireEvent.change(screen.getByLabelText("选择简历文件"), { target: { files: [new File(["# Resume"], "resume.md", { type: "text/markdown" })] } });
    await waitFor(() => expect(api.uploadProfileMaterial).toHaveBeenCalledWith("w1", expect.any(File), expect.objectContaining({ title: "resume" }), expect.any(String)));
  });

  it("uses the unified profile screens and provides one source-review entrance", async () => {
    const material = {
      id: "m1", workspaceId: "w1", type: "resume", title: "后端工程师简历",
      primaryRole: "resume", currentVersionId: "v1", lifecycleStatus: "active",
      version: 1, versionCount: 1, latestProcessingStatus: "ready",
      createdAt: "now", updatedAt: "now",
    };
    const version = {
      id: "v1", materialId: "m1", versionNumber: 1, sourceType: "upload",
      fileName: "resume.md", mimeType: "text/markdown", processingStatus: "ready",
      canRetry: false, createdAt: "now", stages: [],
    };
    api.listProfileMaterials.mockResolvedValue([material]);
    api.listMaterialVersions.mockResolvedValue([version]);
    api.getMaterialVersion.mockResolvedValue({
      ...version,
      material,
      evidencePage: { items: [], offset: 0, limit: 50, total: 0, hasMore: false },
      proposalCounts: { total: 0, pending: 0, accepted: 0, rejected: 0, superseded: 0 },
      execution: null,
    });
    api.getUnifiedProfile.mockResolvedValue({
      ...emptyProfile,
      profileVersion: "pv1",
      isUsable: true,
      pendingCount: 1,
      directions: [{ claimId: "d1", claimVersionId: "dv1", category: "direction", version: 1, title: "后端工程师", subtitle: null, value: { name: "后端工程师" }, supportStatus: "manual", supportSummary: "本人确认", supportEvidence: [], sources: [{ sourceKind: "user_input", label: "本人补充", status: "active" }], linkedTo: [], usedIn: [] }],
      primaryDirectionClaimId: "d1",
      skills: [
        { claimId: "s1", claimVersionId: "sv1", category: "skill", version: 1, title: "FastAPI", subtitle: null, value: { name: "FastAPI" }, supportStatus: "unsupported", supportSummary: "当前简历中没有找到可以直接或相关核对的内容", supportEvidence: [], sources: [{ sourceKind: "resume_extraction", label: "简历提取", status: "active" }], linkedTo: [], usedIn: [] },
        { claimId: "s2", claimVersionId: "sv2", category: "skill", version: 1, title: "灰度发布", subtitle: null, value: { name: "灰度发布" }, supportStatus: "related", supportSummary: "剩余简历中发现相关描述，需要你核对", supportEvidence: [{ evidenceId: "e1", materialTitle: "主投版", versionNumber: 1, section: "项目经历", excerpt: "负责灰度发布", relation: "related" }], sources: [{ sourceKind: "resume_extraction", label: "简历提取", status: "active" }], linkedTo: [], usedIn: [] },
      ],
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "后端工程师" })).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "个人画像页面" });
    for (const name of ["我的画像", "待确认", "来源核对 2", "简历与来源", "画像助手"]) {
      expect(navigation).toHaveTextContent(name);
    }

    fireEvent.click(screen.getByRole("button", { name: "来源核对 2" }));
    expect(await screen.findByRole("heading", { name: "来源核对" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "来源核对" }).closest(".profile-shell")).toHaveClass("profile-shell--workbench");
    expect(document.querySelector(".profile-support-review__list")).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    expect(screen.getByText("灰度发布")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "简历与来源" }));
    expect(await screen.findByRole("region", { name: "简历与来源" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "简历与来源" }).closest(".profile-shell")).toHaveClass("profile-shell--workbench");
    fireEvent.click(screen.getByRole("button", { name: /^待确认/ }));
    expect(await screen.findByRole("heading", { name: "待确认" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "画像助手" }));
    expect(await screen.findByRole("heading", { name: "开始第一次画像对话" })).toBeInTheDocument();
  });

  it("does not request a stale material version after switching workspaces", async () => {
    const material = {
      id: "m1", workspaceId: "w1", type: "resume", title: "测试简历",
      primaryRole: "resume", currentVersionId: "v1", lifecycleStatus: "active",
      version: 1, versionCount: 1, latestProcessingStatus: "ready",
      createdAt: "now", updatedAt: "now",
    };
    const version = {
      id: "v1", materialId: "m1", versionNumber: 1, sourceType: "upload",
      fileName: "resume.md", mimeType: "text/markdown", processingStatus: "ready",
      canRetry: false, createdAt: "now", stages: [],
    };
    api.listProfileMaterials.mockImplementation(async (workspaceId: string) => workspaceId === "w1" ? [material] : []);
    api.listMaterialVersions.mockResolvedValue([version]);
    api.getMaterialVersion.mockResolvedValue({
      ...version,
      material,
      evidencePage: { items: [], offset: 0, limit: 50, total: 0, hasMore: false },
      proposalCounts: { total: 0, pending: 0, accepted: 0, rejected: 0, superseded: 0 },
      execution: null,
    });
    api.getUnifiedProfile.mockImplementation(async (workspaceId: string) => ({ ...emptyProfile, workspaceId }));

    const page = renderPage();
    await waitFor(() => expect(api.getMaterialVersion).toHaveBeenCalledWith("w1", "v1", expect.anything()));

    page.rerenderWorkspace({ id: "w2", workspacePath: "/workspace-2", vaultPath: "/vault-2" });
    await waitFor(() => expect(api.listProfileMaterials).toHaveBeenCalledWith("w2", true, expect.anything()));
    expect(api.getMaterialVersion).not.toHaveBeenCalledWith("w2", "v1", expect.anything());
  });
});
