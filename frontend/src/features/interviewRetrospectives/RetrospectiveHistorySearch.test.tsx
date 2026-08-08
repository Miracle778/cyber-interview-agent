import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RetrospectiveHistorySearch } from "./RetrospectiveHistorySearch";

const api = vi.hoisted(() => ({
  createRetrospectiveSearch: vi.fn(),
  listRetrospectiveSearches: vi.fn(),
  getRetrospectiveSearch: vi.fn(),
  listRetrospectiveSearchResults: vi.fn(),
  summarizeRetrospectiveSearch: vi.fn(),
  createRetrospectiveSearchReport: vi.fn(),
  listRetrospectiveSearchReports: vi.fn(),
  updateRetrospectiveSearchReport: vi.fn(),
}));

vi.mock("./retrospectiveApi", () => api);

function renderSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RetrospectiveHistorySearch workspaceId="w1" targets={[]} />
    </QueryClientProvider>,
  );
}

describe("RetrospectiveHistorySearch", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    api.listRetrospectiveSearches.mockResolvedValue([]);
    api.listRetrospectiveSearchReports.mockResolvedValue([]);
    api.createRetrospectiveSearch.mockResolvedValue({ id: "search-1" });
    api.getRetrospectiveSearch.mockResolvedValue({
      id: "search-1", workspaceId: "w1", queryText: "数字签名", filters: {}, searchPlan: {},
      sessionId: "session-1", executionId: "execution-1", status: "completed",
      totalQuestions: 1, totalRetrospectives: 1, summaryMarkdown: "",
      summaryCitationQuestionIds: [], summaryExecutionId: null, lastErrorCode: null,
      version: 2, completedAt: "now", createdAt: "now", updatedAt: "now",
    });
    api.listRetrospectiveSearchResults.mockResolvedValue([{
      id: "result-1", searchSetId: "search-1", retrospectiveId: "retro-1",
      questionUnitId: "question-1", questionAnalysisId: "analysis-1", rank: 1,
      score: 12, matchedTerms: ["数字签名"], sourceMetadata: { retrospectiveTitle: "字节二面", companyName: "字节跳动" },
      questionSnapshot: { questionText: "数字签名系统如何设计？" }, answerExcerpt: "这是当时的回答。",
      analysisSnapshot: { verdict: "improvable", improvements: [] }, sourceAvailable: true, createdAt: "now",
    }]);
  });

  it("keeps deterministic results readable when no summary was requested", async () => {
    renderSearch();
    fireEvent.change(screen.getByLabelText("搜索历史复盘"), { target: { value: "数字签名" } });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));

    expect(await screen.findByText("数字签名系统如何设计？")).toBeVisible();
    expect(screen.getByText("这是当时的回答。")).toBeVisible();
    expect(screen.getByText("结果集已冻结", { exact: false })).toBeVisible();

    const workspace = screen.getByLabelText("检索结果与分析");
    const search = screen.getByLabelText("历史复盘检索");
    fireEvent.doubleClick(screen.getByRole("tab", { name: "题目详情" }));
    expect(workspace).toHaveClass("is-analysis-expanded");
    expect(search).toHaveClass("is-analysis-expanded");
    expect(screen.getByRole("button", { name: "显示题目列表" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "显示题目列表" }));
    expect(workspace).not.toHaveClass("is-analysis-expanded");
    expect(search).not.toHaveClass("is-analysis-expanded");
  });

  it("keeps summary progress visible after the start request returns", async () => {
    api.summarizeRetrospectiveSearch.mockResolvedValue({
      id: "search-1", workspaceId: "w1", queryText: "数字签名", filters: {}, searchPlan: {},
      sessionId: "session-1", executionId: "execution-1", status: "completed",
      totalQuestions: 1, totalRetrospectives: 1, summaryMarkdown: "",
      summaryCitationQuestionIds: [], summaryExecutionId: "execution-summary", lastErrorCode: null,
      version: 3, completedAt: "now", createdAt: "now", updatedAt: "now",
    });
    renderSearch();
    fireEvent.change(screen.getByLabelText("搜索历史复盘"), { target: { value: "数字签名" } });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));
    await screen.findByText("数字签名系统如何设计？");

    fireEvent.click(screen.getByRole("button", { name: "总结这些问题" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Agent 正在总结当前冻结结果",
    );
    const resultWorkspace = screen.getByLabelText("检索结果与分析");
    expect(resultWorkspace).toContainElement(screen.getByRole("status"));
    expect(screen.getByRole("tab", { name: "Agent 总结" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("数字签名系统如何设计？")).toBeVisible();
  });

  it("restores the latest persisted search after the history tab remounts", async () => {
    api.listRetrospectiveSearches.mockResolvedValue([{
      id: "search-1", workspaceId: "w1", queryText: "数字签名", filters: {}, searchPlan: {},
      sessionId: "session-1", executionId: "execution-1", status: "completed",
      totalQuestions: 1, totalRetrospectives: 1, summaryMarkdown: "",
      summaryCitationQuestionIds: [], summaryExecutionId: null, lastErrorCode: null,
      version: 2, completedAt: "now", createdAt: "now", updatedAt: "now",
    }]);

    renderSearch();

    expect(await screen.findByText("数字签名系统如何设计？")).toBeVisible();
    expect(api.getRetrospectiveSearch).toHaveBeenCalledWith("w1", "search-1", expect.anything());
  });

  it("manages persisted searches in a searchable history drawer", async () => {
    api.listRetrospectiveSearches.mockResolvedValue([
      {
        id: "search-2", workspaceId: "w1", queryText: "找出反复出现的系统设计题", filters: {}, searchPlan: {},
        sessionId: "session-2", executionId: "execution-2", status: "completed",
        totalQuestions: 6, totalRetrospectives: 3, summaryMarkdown: "## 总结",
        summaryCitationQuestionIds: ["question-1"], summaryExecutionId: "execution-summary", lastErrorCode: null,
        version: 2, completedAt: "2026-08-04 01:00:00", createdAt: "2026-08-04 01:00:00", updatedAt: "2026-08-04 01:00:00",
      },
      {
        id: "search-1", workspaceId: "w1", queryText: "帮我找出之前所有关于数字签名项目的问题", filters: {}, searchPlan: {},
        sessionId: "session-1", executionId: "execution-1", status: "completed",
        totalQuestions: 1, totalRetrospectives: 1, summaryMarkdown: "",
        summaryCitationQuestionIds: [], summaryExecutionId: null, lastErrorCode: null,
        version: 2, completedAt: "2026-08-03 09:00:00", createdAt: "2026-08-03 09:00:00", updatedAt: "2026-08-03 09:00:00",
      },
    ]);
    api.getRetrospectiveSearch.mockImplementation((_workspaceId: string, searchSetId: string) => Promise.resolve({
      id: searchSetId, workspaceId: "w1",
      queryText: searchSetId === "search-2" ? "找出反复出现的系统设计题" : "帮我找出之前所有关于数字签名项目的问题",
      filters: {}, searchPlan: {}, sessionId: "session", executionId: "execution", status: "completed",
      totalQuestions: 1, totalRetrospectives: 1, summaryMarkdown: "", summaryCitationQuestionIds: [],
      summaryExecutionId: null, lastErrorCode: null, version: 2, completedAt: "now", createdAt: "now", updatedAt: "now",
    }));

    renderSearch();
    expect(await screen.findByRole("region", { name: "当前历史检索" })).toHaveTextContent("找出反复出现的系统设计题");
    fireEvent.click(screen.getByRole("button", { name: /检索记录/ }));

    const drawer = screen.getByRole("dialog", { name: "检索记录" });
    expect(drawer).toHaveTextContent("8/4 09:00");
    expect(drawer).toHaveTextContent("帮我找出之前所有关于数字签名项目的问题");
    fireEvent.change(screen.getByLabelText("筛选检索记录"), { target: { value: "数字签名" } });
    expect(drawer).not.toHaveTextContent("反复出现的系统设计题");
    fireEvent.click(screen.getByRole("button", { name: "再次检索：帮我找出之前所有关于数字签名项目的问题" }));

    await waitFor(() => expect(api.createRetrospectiveSearch).toHaveBeenCalledWith(
      "w1", "帮我找出之前所有关于数字签名项目的问题", { jobTargetId: null },
    ));
  });

  it("configures a report against the frozen result set", async () => {
    api.createRetrospectiveSearchReport.mockResolvedValue({
      id: "report-1", workspaceId: "w1", searchSetId: "search-1", reportKey: "key-1",
      ordinal: 1, supersedesReportId: null, executionId: "execution-2", title: "数字签名专项",
      focus: "preparation", selectedResultIds: [], body: {}, markdown: "", citationQuestionIds: [],
      includeAnswerExcerpts: true, includeActionPlan: true, status: "queued", lastErrorCode: null,
      version: 1, completedAt: null, createdAt: "now", updatedAt: "now",
    });
    renderSearch();
    fireEvent.change(screen.getByLabelText("搜索历史复盘"), { target: { value: "数字签名" } });
    fireEvent.click(screen.getByRole("button", { name: "开始检索" }));
    await screen.findByText("数字签名系统如何设计？");

    fireEvent.click(screen.getByRole("button", { name: "生成总结报告" }));
    expect(screen.getByRole("dialog", { name: "生成历史复盘报告" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("历史报告名称"), { target: { value: "数字签名专项" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));

    await waitFor(() => expect(api.createRetrospectiveSearchReport).toHaveBeenCalledWith(
      "w1", "search-1", expect.objectContaining({ title: "数字签名专项", focus: "preparation" }),
    ));
  });

  it("restores a saved report and its frozen sources after refresh", async () => {
    api.listRetrospectiveSearchReports.mockResolvedValue([{
      id: "report-1", workspaceId: "w1", searchSetId: "search-1", reportKey: "key-1",
      ordinal: 1, supersedesReportId: null, executionId: "execution-2", title: "数字签名专项",
      focus: "preparation", selectedResultIds: ["result-1"], body: {}, markdown: "## 主要发现\n需要补充 PKI 设计细节。",
      citationQuestionIds: ["question-1"], includeAnswerExcerpts: true, includeActionPlan: true,
      status: "completed", lastErrorCode: null, version: 2, completedAt: "now", createdAt: "now", updatedAt: "now",
    }]);

    renderSearch();
    expect(await screen.findByRole("button", { name: /数字签名专项/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /数字签名专项/ }));

    expect(await screen.findByText("主要发现")).toBeVisible();
    expect(screen.getByText("引用来源（1）")).toBeVisible();
    expect(await screen.findByText("数字签名系统如何设计？")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看来源结果" }));
    await waitFor(() => expect(api.getRetrospectiveSearch).toHaveBeenCalledWith("w1", "search-1", expect.anything()));
  });
});
