import { expect, test } from "@playwright/test";

const QUESTION = {
  id: "q-middleware",
  title: "Middleware 验收题",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "查询不存在的数据导致缓存无法命中。",
  topics: ["cache"],
  difficulty: "medium",
  keyPoints: ["空值缓存", "布隆过滤器"],
  followUps: [],
  mastery: "weak",
};

test("runtime middleware exposes usage title and persistent review state", async ({ page, request }) => {
  const messages: string[] = [];
  page.on("console", (message) => {
    if (["warning", "error"].includes(message.type())) messages.push(message.text());
  });

  const workspaceResponse = await request.post("http://127.0.0.1:8017/api/settings/workspaces", {
    data: { rootPath: "/private/tmp/cyber-r16-e2e-workspace" },
  });
  const workspace = await workspaceResponse.json();
  const providerResponse = await request.post("http://127.0.0.1:8017/api/settings/providers", {
    data: { name: "Middleware E2E", apiFormat: "openai-compatible", baseUrl: "http://127.0.0.1:9017/v1", secretSource: "environment", secretRef: "R16_E2E_API_KEY" },
  });
  const provider = await providerResponse.json();
  const modelResponse = await request.post(`http://127.0.0.1:8017/api/settings/providers/${provider.id}/models`, {
    data: { modelId: "middleware-model", displayName: "Middleware Model" },
  });
  const model = await modelResponse.json();
  await request.put(`http://127.0.0.1:8017/api/settings/workspaces/${workspace.id}/model-bindings`, {
    data: { bindings: Object.fromEntries(["question_generation", "answer_evaluation", "report_summarization", "agent_chat"].map((role) => [role, model.id])) },
  });

  const sessionResponse = await request.post("http://127.0.0.1:8017/api/agent/sessions", {
    data: { workspaceId: workspace.id, graphId: "review.single", graphVersion: 1, title: "新会话" },
  });
  const session = await sessionResponse.json();
  await request.post(`http://127.0.0.1:8017/api/agent/sessions/${session.id}/runs`, {
    data: { input: { question: QUESTION, text: "缓存空值", user_answer: "缓存空值" } },
  });
  await expect.poll(async () => {
    const detail = await (await request.get(`http://127.0.0.1:8017/api/agent/sessions/${session.id}`)).json();
    return detail.latestRun.status;
  }).toBe("waiting_for_approval");

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/review");
  await expect(page.getByLabel("运行用量")).toContainText("tokens");
  await expect(page.getByRole("button", { name: "批准发布" })).toBeVisible();
  await page.getByRole("button", { name: "批准发布" }).click();
  await expect(page.getByText("草稿状态：published")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("历史会话")).not.toHaveText("新会话");
  await expect(page.getByLabel("运行用量")).toContainText("tokens");
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBeFalsy();

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBeFalsy();
  expect(messages).toEqual([]);
});
