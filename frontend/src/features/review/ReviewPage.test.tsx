import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { WorkspaceConfig } from "../settings/settingsApi";
import type { PendingAction } from "../agent/hitlTypes";
import type { KnowledgeSource } from "../knowledge/knowledgeTypes";
import { ReviewPage } from "./ReviewPage";
import type { ActiveQuestion, ReviewRound } from "./reviewTypes";

class FakeEventSource {
  onopen = null;
  onerror = null;
  addEventListener() {}
  close() {}
}

const workspace: WorkspaceConfig = { id: "w1", workspacePath: "/tmp/demo", vaultPath: "/tmp/demo/vault" };
const waitingRound: ReviewRound = {
  id: "round-1", workspaceId: "w1", sessionId: "session-1", executionId: "run-1",
  settings: { topics: [], difficulties: ["medium"], mode: "random-mixed", question_count: 2, allow_follow_up: true, seed: 1, answer_model_id: "model-1", reasoning_effort: "medium" },
  status: "waiting_for_input", executionStatus: "waiting_for_input", currentIndex: 0, questionCount: 2,
  currentQuestion: { id: "q1", title: "MVCC", questionText: "Read View 如何判断可见性？", topics: ["database"], difficulty: "medium" },
  currentInput: { id: "input-1", roundId: "round-1", ordinal: 1, kind: "answer", prompt: "Read View 如何判断可见性？", version: 1, status: "pending", createdAt: "now", resolvedAt: null },
  attempts: [], reports: [], usage: { inputTokens: 12, outputTokens: 4, totalTokens: 16, callCount: 1, estimatedCount: 0 }, contextUsage: { currentTokens: 32000, thresholdTokens: 89600, estimated: true }, createdAt: "now", updatedAt: "now", completedAt: null,
  messages: [],
};

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider></MemoryRouter>;
}

function wrapperAt(entry: string) {
  return function RouteWrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[entry]}><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider></MemoryRouter>;
  };
}

function activeQuestions(count: number): ActiveQuestion[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `q-${index}`,
    draftId: `d-${index}`,
    publicationId: `p-${index}`,
    publishedAt: "now",
    title: `Question ${index + 1}`,
    questionText: "Question body",
    referenceAnswer: "Reference answer",
    topics: ["database"],
    difficulty: "medium",
    keyPoints: ["point"],
    followUps: [],
  }));
}

function mockApi(rounds: ReviewRound[], questions: ActiveQuestion[] = [], actions: PendingAction[] = [], sources: KnowledgeSource[] = []) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/review/rounds/round-1/retry" && init?.method === "POST") return Response.json({ ...rounds[0], executionStatus: "running" }, { status: 202 });
    if (url.includes("/api/review/rounds?")) return Response.json(rounds);
    if (url === "/api/review/rounds/round-1") return Response.json(rounds[0]);
    if (url.includes("/api/review/questions?")) return Response.json(questions);
    if (url.includes("/api/knowledge/sources?")) return Response.json(sources);
    if (url === "/api/settings/providers") return Response.json([]);
    if (url.includes("/model-bindings")) return Response.json({ workspaceId: "w1", bindings: {} });
    if (url.includes("/api/agent/sessions/session-1")) return Response.json({});
    if (url.includes("/api/agent/actions?")) return Response.json(actions);
    throw new Error(`unexpected ${url}`);
  });
}

describe("R2 ReviewPage", () => {
  beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("separates question curation and review as primary entries", async () => {
    mockApi([]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    const navigation = await screen.findByRole("navigation", { name: "复习工作台入口" });
    const practiceEntry = within(navigation).getByRole("button", { name: /开始复习/ });
    const catalogEntry = within(navigation).getByRole("button", { name: /题库整理/ });
    expect(practiceEntry).toHaveAttribute("aria-current", "page");
    expect(practiceEntry.compareDocumentPosition(catalogEntry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByRole("button", { name: "创建复习" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "题库尚未准备好" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "去题库整理" }));
    expect(await screen.findByRole("heading", { name: "题库整理" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建复习" })).toBeNull();
  });

  it("defaults to history and enters a selected round without showing HITL", async () => {
    mockApi([waitingRound]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    expect(await screen.findByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "当前复习轮次" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("region", { name: "当前复习轮次" })).toHaveTextContent("Read View 如何判断可见性？");
    const feedback = screen.getByLabelText("本题反馈");
    expect(feedback).toHaveTextContent("model-1");
    expect(feedback).toHaveTextContent("中等思考");
    expect(feedback).toHaveTextContent("16");
    expect(feedback).toHaveTextContent("32k / 90k");
    expect(feedback).toHaveTextContent("36%");
    expect(screen.getByRole("navigation", { name: "本轮题目进度" })).toHaveTextContent("MVCC");
    expect(screen.queryByRole("navigation", { name: "复习轮次历史" })).not.toBeInTheDocument();
    expect(screen.queryByText("待确认操作")).toBeNull();
  });

  it("opens a run-center deep link at the exact review round and offers a quick return", async () => {
    mockApi([waitingRound]);
    render(<ReviewPage workspace={workspace} />, {
      wrapper: wrapperAt(
        "/review?section=practice&reviewSessionId=session-1&returnTo=%2Fagents%3Fstatus%3Dneeds_me",
      ),
    });

    expect(await screen.findByRole("region", { name: "当前复习轮次" })).toHaveTextContent(
      "Read View 如何判断可见性？",
    );
    expect(screen.getByRole("link", { name: "返回任务运行" })).toHaveAttribute(
      "href",
      "/agents?status=needs_me",
    );
  });

  it("opens completed and skipped questions in read-only review mode and returns to the active question", async () => {
    const roundWithHistory = {
      ...waitingRound,
      currentIndex: 2,
      questionCount: 3,
      currentQuestion: { ...waitingRound.currentQuestion!, id: "q3", title: "当前题目", questionText: "当前题目原文" },
      currentInput: { ...waitingRound.currentInput!, ordinal: 3, prompt: "当前题目原文" },
      attempts: [
        {
          id: "attempt-1",
          roundId: "round-1",
          ordinal: 1,
          questionSnapshot: { questionId: "q1", documentId: "d1", contentHash: "h1", title: "已完成题目", questionText: "完成题原文", referenceAnswer: "完成题答案", topics: ["database"], difficulty: "medium", keyPoints: ["版本链"], followUps: [] },
          answer: "我的完成题回答",
          followUpAnswer: null,
          evaluation: { score: "good", missing_key_points: [], evidence: "回答覆盖完整", mastery_suggestion: "strong" },
          masterySuggestion: "strong",
          skipped: false,
          status: "completed",
          evaluationErrorCode: null,
          evaluationStartedAt: "now",
          evaluationCompletedAt: "now",
          resultKind: "independent_mastery",
          createdAt: "now",
          updatedAt: "now",
        },
        {
          id: "attempt-2",
          roundId: "round-1",
          ordinal: 2,
          questionSnapshot: { questionId: "q2", documentId: "d2", contentHash: "h2", title: "已跳过题目", questionText: "跳过题原文", referenceAnswer: "跳过题答案", topics: ["cache"], difficulty: "medium", keyPoints: ["缓存"], followUps: [] },
          answer: null,
          followUpAnswer: null,
          evaluation: null,
          masterySuggestion: null,
          skipped: true,
          status: "completed",
          evaluationErrorCode: null,
          evaluationStartedAt: null,
          evaluationCompletedAt: null,
          resultKind: "skipped",
          createdAt: "now",
          updatedAt: "now",
        },
      ],
    } as ReviewRound;
    mockApi([roundWithHistory]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: /3 题/ }));
    fireEvent.click(await screen.findByRole("button", { name: /回看第 1 题：已完成题目，已完成/ }));
    expect(screen.getByRole("region", { name: "回看第 1 题" })).toHaveTextContent("我的完成题回答");
    expect(screen.getByRole("region", { name: "回看第 1 题" })).toHaveTextContent("回答覆盖完整");

    fireEvent.click(screen.getByRole("button", { name: "返回当前第 3 题" }));
    expect(await screen.findByRole("region", { name: "当前题目" })).toHaveTextContent("当前题目原文");

    fireEvent.click(screen.getByRole("button", { name: /回看第 2 题：已跳过题目，已跳过/ }));
    expect(screen.getByRole("region", { name: "回看第 2 题" })).toHaveTextContent("主动跳过");
    expect(screen.getByRole("region", { name: "回看第 2 题" })).toHaveTextContent("回看不会改变答题进度");
  });

  it("expands omitted questions and opens a hidden completed question", async () => {
    const attempts = Array.from({ length: 7 }, (_, index) => {
      const ordinal = index + 1;
      return {
        id: `attempt-${ordinal}`,
        roundId: "round-1",
        ordinal,
        questionSnapshot: { questionId: `q${ordinal}`, documentId: `d${ordinal}`, contentHash: `h${ordinal}`, title: `历史题目 ${ordinal}`, questionText: `第 ${ordinal} 题原文`, referenceAnswer: `第 ${ordinal} 题答案`, topics: ["database"], difficulty: "medium", keyPoints: ["关键点"], followUps: [] },
        answer: `第 ${ordinal} 题回答`,
        followUpAnswer: null,
        evaluation: { score: "good", missing_key_points: [], evidence: "回答完整", mastery_suggestion: "strong" },
        masterySuggestion: "strong",
        skipped: ordinal === 7,
        status: "completed",
        evaluationErrorCode: null,
        evaluationStartedAt: "now",
        evaluationCompletedAt: "now",
        resultKind: ordinal === 7 ? "skipped" : "independent_mastery",
        createdAt: "now",
        updatedAt: "now",
      };
    }) as ReviewRound["attempts"];
    const roundWithOmittedHistory = {
      ...waitingRound,
      currentIndex: 7,
      questionCount: 10,
      currentQuestion: { ...waitingRound.currentQuestion!, id: "q8", title: "当前第 8 题", questionText: "当前第 8 题原文" },
      currentInput: { ...waitingRound.currentInput!, ordinal: 8, prompt: "当前第 8 题原文" },
      attempts,
    } as ReviewRound;
    mockApi([roundWithOmittedHistory]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: /10 题/ }));
    const omitted = await screen.findByRole("button", { name: "查看第 2 至 6 题" });
    expect(omitted).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(omitted);
    expect(omitted).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "回看第 4 题：历史题目 4，已完成" }));

    expect(screen.getByRole("region", { name: "回看第 4 题" })).toHaveTextContent("第 4 题回答");
    expect(screen.queryByRole("region", { name: "第 2 至 6 题" })).toBeNull();
  });

  it("shows completed results without reopening setup", async () => {
    mockApi([{ ...waitingRound, status: "completed", executionStatus: "completed", currentQuestion: null, currentInput: null, completedAt: "later" }]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    await screen.findByRole("heading", { name: "复习历史" });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByText("本轮复习结果")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "答题回顾" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "会话回放" })).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });

  it("shows the pending report content and confirmation controls beside results", async () => {
    const reportRound = {
      ...waitingRound,
      status: "report_pending",
      executionStatus: "waiting_for_approval",
      currentIndex: 2,
      currentQuestion: null,
      currentInput: null,
      reports: [
        { id: "draft-report", reportKind: "session_report", title: "本轮复习报告", markdown: "# 本轮复习报告\n\n需要继续复习数据库可见性。", status: "review_pending", version: 1, publication: null },
        { id: "draft-mastery", reportKind: "mastery_report", title: "掌握度更新", markdown: "# 掌握度更新\n\n数据库主题仍需加强。", status: "review_pending", version: 1, publication: null },
      ],
    } as ReviewRound;
    const action = {
      id: "action-report",
      workspaceId: "w1",
      sessionId: "session-1",
      executionId: "run-1",
      actionType: "knowledge.publish",
      preview: {
        title: "本轮复习报告",
        markdown: "# 本轮复习报告\n\n需要继续复习数据库可见性。",
        draftId: "draft-report",
        reportKind: "session_report",
      },
      editableFields: ["title", "markdown"],
      status: "pending",
      version: 1,
      createdAt: "now",
      resolvedAt: null,
    } as PendingAction;
    mockApi([reportRound], [], [action]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));

    const approval = await screen.findByRole("complementary", { name: "报告确认区" });
    expect(within(approval).getByText("报告确认")).toBeInTheDocument();
    await waitFor(() => expect(within(approval).getByRole("region", { name: "待确认报告预览" })).toHaveTextContent("需要继续复习数据库可见性"));
    expect(within(approval).getByRole("button", { name: /复习报告 当前待确认/ })).toHaveAttribute("aria-current", "step");
    expect(within(approval).getByRole("button", { name: "确认并保存报告" })).toBeInTheDocument();
    expect(approval).not.toHaveTextContent("draft-report");
    expect(approval).not.toHaveTextContent("session_report");

    fireEvent.click(screen.getByRole("tab", { name: "报告 2" }));
    const masteryArtifact = screen.getByText("确认后会更新后续复习使用的掌握度。").closest("article")!;
    fireEvent.click(within(masteryArtifact).getByRole("button", { name: "查看确认顺序" }));
    expect(await within(approval).findByText("这份报告还不能确认")).toBeInTheDocument();
    expect(within(approval).getByRole("button", { name: /掌握度更新 等待上一份/ })).toHaveAttribute("aria-current", "step");

    fireEvent.click(within(approval).getByRole("button", { name: /复习报告 当前待确认/ }));
    expect(await within(approval).findByRole("button", { name: "确认并保存报告" })).toBeInTheDocument();

    fireEvent.click(within(approval).getByRole("button", { name: "收起报告确认，展开复习结果" }));
    expect(screen.getByRole("button", { name: "展开报告确认" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开报告确认" }));
    fireEvent.click(screen.getByRole("button", { name: "收起复习结果，展开报告确认" }));
    expect(screen.getByRole("button", { name: "展开复习结果" })).toBeInTheDocument();
  });

  it("keeps the report workspace stable between approvals and reopens confirmed reports", async () => {
    const transitionRound = {
      ...waitingRound,
      status: "report_pending",
      executionStatus: "running",
      currentIndex: 2,
      currentQuestion: null,
      currentInput: null,
      reports: [
        {
          id: "draft-report",
          reportKind: "session_report",
          title: "本轮复习报告",
          markdown: "# 本轮复习报告\n\n已确认报告正文。",
          status: "published",
          version: 1,
          publication: { state: "completed", target_path: "20_review_sessions/report.md", error_code: null },
        },
        {
          id: "draft-mastery",
          reportKind: "mastery_report",
          title: "掌握度更新",
          markdown: "# 掌握度更新\n\n等待确认。",
          status: "review_pending",
          version: 1,
          publication: null,
        },
      ],
    } as ReviewRound;
    mockApi([transitionRound], [], []);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("complementary", { name: "报告确认区" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "报告 2" }));
    const confirmedArtifact = screen.getByText("这份复习报告已经保存，可随时回看。").closest("article")!;
    fireEvent.click(within(confirmedArtifact).getByRole("button", { name: "查看报告" }));

    const approval = screen.getByRole("complementary", { name: "报告确认区" });
    expect(within(approval).getByRole("heading", { name: "报告详情" })).toBeInTheDocument();
    expect(within(approval).getByText("已确认报告正文。")).toBeInTheDocument();
    expect(within(approval).getByRole("button", { name: /复习报告 已确认/ })).toHaveAttribute("aria-current", "step");
    expect(within(approval).getByRole("button", { name: /掌握度更新 正在准备/ })).toBeInTheDocument();
  });

  it("shows a recovery action instead of a broken active conversation", async () => {
    const failed = { ...waitingRound, executionStatus: "failed", currentInput: null } as ReviewRound;
    const fetch = mockApi([failed]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("status", { name: "复习轮次需要恢复" })).toHaveTextContent("回答和评价记录都已保留");
    fireEvent.click(screen.getByRole("button", { name: "恢复本轮" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/review/rounds/round-1/retry", expect.objectContaining({ method: "POST" })));
  });

  it("shows an explicit ended state for an empty cancelled round", async () => {
    const ended = { ...waitingRound, status: "cancelled", executionStatus: "cancelled", currentQuestion: null, currentInput: null } as ReviewRound;
    mockApi([ended]);
    render(<ReviewPage workspace={workspace} />, { wrapper });
    fireEvent.click(await screen.findByRole("button", { name: /2 题/ }));
    expect(await screen.findByRole("status", { name: "复习轮次已结束" })).toHaveTextContent("尚未产生回答记录");
  });

  it("opens and closes creation as a distinct panel", async () => {
    mockApi([], activeQuestions(10));
    render(<ReviewPage workspace={workspace} />, { wrapper });
    const createButton = await screen.findByRole("button", { name: "创建复习" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    expect(await screen.findByText("创建复习轮次")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回历史" }));
    expect(await screen.findByRole("heading", { name: "复习历史" })).toBeInTheDocument();
    expect(screen.queryByText("创建复习轮次")).toBeNull();
  });

  it("keeps a large topic catalog compact until the user expands or searches it", async () => {
    const questions = activeQuestions(24).map((question, index) => ({
      ...question,
      topics: [`主题 ${String(index + 1).padStart(2, "0")}`],
    }));
    mockApi([], questions);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    const createButton = await screen.findByRole("button", { name: "创建复习" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);

    expect(await screen.findByRole("button", { name: "展开全部（24）" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(18);
    expect(screen.queryByRole("checkbox", { name: "主题 24" })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "搜索复习主题" }), { target: { value: "主题 24" } });
    expect(screen.getByRole("checkbox", { name: "主题 24" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("selects a source file and derives the actual round size from its questions", async () => {
    const questions = activeQuestions(3).map((question, index) => ({
      ...question,
      sourceIds: index < 2 ? ["source-a"] : ["source-b"],
    }));
    mockApi([], questions, [], [
      { id: "source-a", workspaceId: "w1", originalFilename: "MyBatis 拦截器.md", storedPath: "sources/a.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null },
      { id: "source-b", workspaceId: "w1", originalFilename: "Redis 笔记.md", storedPath: "sources/b.md", contentType: "text/markdown", sizeBytes: 20, createdAt: "now", draftId: null },
    ]);
    render(<ReviewPage workspace={workspace} />, { wrapper });

    const createButton = await screen.findByRole("button", { name: "创建复习" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    fireEvent.change(screen.getByLabelText("复习模式"), { target: { value: "source-file" } });
    const sourceSelect = await screen.findByRole("combobox", { name: "选择复习资料" });
    await waitFor(() => expect(sourceSelect).toHaveTextContent("MyBatis 拦截器.md（2 道）"));
    fireEvent.change(sourceSelect, { target: { value: "source-a" } });

    expect(screen.getByText("匹配题目 2 道")).toBeInTheDocument();
    expect(screen.getByText("本轮计划 2 道")).toBeInTheDocument();
    expect(screen.getByText("该资料不足 10 道，将按实际题量创建")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "复习主题" })).toBeNull();
  });
});
