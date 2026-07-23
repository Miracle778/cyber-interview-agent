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
  });

  it("shows loading then the upload empty state and validates picker/drop files", async () => {
    let resolveMaterials!: (value: []) => void;
    api.listProfileMaterials.mockReturnValueOnce(new Promise((resolve) => { resolveMaterials = resolve; }));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("正在读取个人材料");
    resolveMaterials([]);
    expect(await screen.findByText("还没有个人材料")).toBeInTheDocument();

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
    expect(await screen.findByRole("alert")).toHaveTextContent("个人材料读取失败");
    api.listProfileMaterials.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(await screen.findByText("还没有个人材料")).toBeInTheDocument();

    api.uploadProfileMaterial.mockResolvedValue({ materialId: "m1", versionId: "v1", executionId: "e1", processingStatus: "uploaded" });
    fireEvent.change(screen.getByLabelText("选择简历文件"), { target: { files: [new File(["# Resume"], "resume.md", { type: "text/markdown" })] } });
    await waitFor(() => expect(api.uploadProfileMaterial).toHaveBeenCalledWith("w1", expect.any(File), expect.objectContaining({ title: "resume" }), expect.any(String)));
  });
});
