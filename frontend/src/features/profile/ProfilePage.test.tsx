import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
}));

vi.mock("./profileApi", () => api);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><ProfilePage workspace={{ id: "w1", workspacePath: "/workspace", vaultPath: "/vault" }} /></QueryClientProvider>);
}

describe("ProfilePage", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    api.listProfileMaterials.mockResolvedValue([]);
    api.listMaterialVersions.mockResolvedValue([]);
    api.listProfileClaims.mockResolvedValue({ workspaceId: "w1", profileVersion: null, claims: [], proposals: [] });
    api.listProfileSessions.mockResolvedValue([]);
  });

  it("shows loading then the upload empty state and validates picker/drop files", async () => {
    let resolveMaterials!: (value: []) => void;
    api.listProfileMaterials.mockReturnValueOnce(new Promise((resolve) => { resolveMaterials = resolve; }));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取简历");
    resolveMaterials([]);
    expect(await screen.findByText("还没有简历")).toBeInTheDocument();

    const picker = screen.getByLabelText("选择简历文件");
    fireEvent.change(picker, { target: { files: [new File(["x"], "resume.exe")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("支持 PDF、DOCX、Markdown 或 TXT");

    const tooLarge = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "resume.pdf", { type: "application/pdf" });
    fireEvent.drop(screen.getByTestId("profile-dropzone"), { dataTransfer: { files: [tooLarge] } });
    expect(screen.getByRole("alert")).toHaveTextContent("不能超过 10 MB");
    expect(api.uploadProfileMaterial).not.toHaveBeenCalled();
  });

  it("uploads a valid resume and gives an actionable retry when loading fails", async () => {
    api.listProfileMaterials.mockRejectedValueOnce(new Error("offline"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("简历读取失败");
    api.listProfileMaterials.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(await screen.findByText("还没有简历")).toBeInTheDocument();

    api.uploadProfileMaterial.mockResolvedValue({ materialId: "m1", versionId: "v1", executionId: "e1", processingStatus: "uploaded" });
    fireEvent.change(screen.getByLabelText("选择简历文件"), { target: { files: [new File(["# Resume"], "resume.md", { type: "text/markdown" })] } });
    await waitFor(() => expect(api.uploadProfileMaterial).toHaveBeenCalledWith("w1", expect.any(File), expect.objectContaining({ title: "resume" }), expect.any(String)));
  });

  it("keeps the four-screen contract and explains confirmed-only downstream use", async () => {
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

    renderPage();

    expect(await screen.findByText("只有确认过的信息才会用于后续准备")).toBeInTheDocument();
    expect(screen.getByText(/待确认、已拒绝和敏感信息不会自动使用/)).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "我的简历页面" });
    for (const name of ["概览", "简历与版本", "确认简历要点", "简历助手"]) {
      expect(navigation).toHaveTextContent(name);
    }

    fireEvent.click(screen.getByRole("button", { name: "简历与版本" }));
    expect(await screen.findByRole("region", { name: "简历与版本" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认简历要点" }));
    expect(await screen.findByRole("heading", { name: "确认简历要点" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "简历助手" }));
    expect(await screen.findByRole("heading", { name: "开始使用简历助手" })).toBeInTheDocument();
  });
});
