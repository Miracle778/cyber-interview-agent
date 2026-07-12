import { expect, test } from "@playwright/test";
import { readdirSync } from "node:fs";


const QUESTION = {
  id: "q-reject",
  title: "拒绝路径题目",
  questionText: "事务隔离性是什么？",
  referenceAnswer: "隔离性限制并发事务的相互影响。",
  topics: ["database"],
  difficulty: "medium",
  keyPoints: ["并发事务", "隔离级别"],
  followUps: [],
  mastery: "weak",
};


test("single review runs through provider runtime HITL and Vault", async ({ page, request }) => {
  const workspaceResponse = await request.post("http://127.0.0.1:8017/api/settings/workspaces", {
    data: { rootPath: "/private/tmp/cyber-r16-e2e-workspace" },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();

  const providerResponse = await request.post("http://127.0.0.1:8017/api/settings/providers", {
    data: {
      name: "E2E OpenAI",
      apiFormat: "openai-compatible",
      baseUrl: "http://127.0.0.1:9017/v1",
      secretSource: "environment",
      secretRef: "R16_E2E_API_KEY",
    },
  });
  expect(providerResponse.ok()).toBeTruthy();
  const provider = await providerResponse.json();
  const modelResponse = await request.post(
    `http://127.0.0.1:8017/api/settings/providers/${provider.id}/models`,
    { data: { modelId: "e2e-model", displayName: "E2E Model" } },
  );
  expect(modelResponse.ok()).toBeTruthy();
  const model = await modelResponse.json();
  const connectionResponse = await request.post(
    `http://127.0.0.1:8017/api/settings/provider-models/${model.id}/test`,
  );
  expect(connectionResponse.ok()).toBeTruthy();
  expect((await connectionResponse.json()).connectivityStatus).toBe("ok");

  const bindings = Object.fromEntries(
    ["question_generation", "answer_evaluation", "report_summarization", "agent_chat"].map(
      (role) => [role, model.id],
    ),
  );
  const bindingResponse = await request.put(
    `http://127.0.0.1:8017/api/settings/workspaces/${workspace.id}/model-bindings`,
    { data: { bindings } },
  );
  expect(bindingResponse.ok()).toBeTruthy();

  await page.goto("/knowledge");
  await page.getByLabel("选择资料文件").setInputFiles({
    name: "acid.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("事务 ACID 包含原子性、一致性、隔离性、持久性。", "utf-8"),
  });
  await page.getByRole("button", { name: "上传资料" }).click();
  await expect(page.getByRole("heading", { name: "题库草稿" })).toBeVisible();

  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "复习" }).click();
  await page.getByLabel("你的回答").fill("事务保证原子性和一致性");
  await page.getByRole("button", { name: "发送回答" }).click();

  await expect(page.getByText("评分：partial", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("草稿状态：review_pending")).toBeVisible();
  await expect(page.getByRole("button", { name: "批准发布" })).toBeVisible();

  await page.reload();
  await expect(page.getByText("事务保证原子性和一致性")).toBeVisible();
  await expect(page.getByText("草稿状态：review_pending")).toBeVisible();
  await page.getByRole("button", { name: "批准发布" }).click();

  await expect(page.getByText("草稿状态：published")).toBeVisible();
  await expect(page.getByText("发布状态：completed")).toBeVisible();
  await expect(page.getByText(/目标路径：.*20_review_sessions/)).toBeVisible();

  const resolvedActionsResponse = await request.get(
    `http://127.0.0.1:8017/api/agent/actions?workspaceId=${workspace.id}`,
  );
  const resolvedActions = await resolvedActionsResponse.json();
  const approvedAction = resolvedActions.find((item: { status: string }) => item.status === "approved");
  const repeatedApproval = await request.post(
    `http://127.0.0.1:8017/api/agent/actions/${approvedAction.id}/approve`,
    { data: { version: approvedAction.version, idempotencyKey: "repeat-approval" } },
  );
  expect(repeatedApproval.status()).toBe(409);

  const secondSessionResponse = await request.post(
    "http://127.0.0.1:8017/api/agent/sessions",
    {
      data: {
        workspaceId: workspace.id,
        graphId: "review.single",
        graphVersion: 1,
        title: "单题复习：拒绝路径",
      },
    },
  );
  const secondSession = await secondSessionResponse.json();
  const secondRunResponse = await request.post(
    `http://127.0.0.1:8017/api/agent/sessions/${secondSession.id}/runs`,
    {
      data: {
        input: {
          question: QUESTION,
          text: "只回答了并发事务",
          user_answer: "只回答了并发事务",
        },
      },
    },
  );
  expect(secondRunResponse.status()).toBe(202);
  await expect.poll(async () => {
    const response = await request.get(
      `http://127.0.0.1:8017/api/agent/sessions/${secondSession.id}`,
    );
    return (await response.json()).latestRun.status;
  }).toBe("waiting_for_approval");

  await page.reload();
  await expect(page.getByText("拒绝路径题目")).toBeVisible();
  await page.getByLabel("拒绝原因").fill("报告需要补充");
  await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.getByText("草稿状态：rejected")).toBeVisible();

  const vaultFiles = readdirSync(
    "/private/tmp/cyber-r16-e2e-workspace/knowledge-vault",
    { recursive: true },
  ).filter((name) => String(name).endsWith(".md"));
  expect(vaultFiles).toHaveLength(1);

  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBeFalsy();
});
