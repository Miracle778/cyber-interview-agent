import { expect, test } from "@playwright/test";


test("knowledge workspace completes the responsive publication flow", async ({ page, request }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      browserErrors.push(`${message.type()}: ${message.text()}`);
    }
  });

  const workspaceResponse = await request.post(
    "http://127.0.0.1:8017/api/settings/workspaces",
    { data: { rootPath: "/private/tmp/cyber-r16-e2e-workspace" } },
  );
  expect(workspaceResponse.ok()).toBeTruthy();

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/knowledge");
  await expect(page.getByRole("heading", { name: "人工确认" })).toHaveCount(0);

  await page.getByLabel("选择资料文件").setInputFiles({
    name: "cache.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# 缓存穿透\n\n缓存穿透是查询不存在的数据，导致请求绕过缓存。\n\n- 缓存空值\n- 布隆过滤器",
      "utf-8",
    ),
  });
  await page.getByRole("button", { name: "上传资料" }).click();

  await expect(page.getByRole("region", { name: "原始资料" })).toContainText("cache.md");
  await expect(page.getByRole("region", { name: "生成草稿" })).toContainText("草稿");
  await expect(page.getByRole("article")).toContainText("缓存穿透");
  await expect(page.getByRole("article")).not.toContainText("status: draft");

  await page.getByRole("button", { name: "编辑" }).click();
  await page.getByRole("button", { name: "取消编辑" }).click();
  await page.getByRole("button", { name: "编辑" }).click();
  await page.getByRole("textbox", { name: "标题" }).fill("缓存穿透验收题");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("草稿已保存")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Markdown 正文" })).toHaveCount(0);

  await page.getByRole("button", { name: "上传资料" }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "重新扫描 Vault" })).toBeFocused();

  await page.getByRole("button", { name: "请求发布" }).click();
  await expect(page.getByRole("heading", { name: "人工确认" })).toBeVisible();
  await page.getByRole("button", { name: "批准" }).click();
  await expect(page.getByRole("heading", { name: "人工确认" })).toHaveCount(0);
  await expect(page.getByText(/已发布路径：knowledge-vault\/10_question_bank\//)).toBeVisible();

  await page.reload();
  await expect(page.getByRole("region", { name: "原始资料" })).toContainText("cache.md");
  await expect(page.getByRole("region", { name: "生成草稿" })).toContainText("已发布");
  await expect(page.getByRole("heading", { name: "人工确认" })).toHaveCount(0);

  const desktopOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(desktopOverflow).toBeFalsy();

  await page.setViewportSize({ width: 375, height: 812 });
  const mobileOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(mobileOverflow).toBeFalsy();
  await expect(page.getByRole("region", { name: "原始资料" })).toBeVisible();
  await expect(page.getByRole("region", { name: "生成草稿" })).toBeVisible();
  await expect(page.getByRole("region", { name: "知识内容" })).toBeVisible();
  expect(browserErrors).toEqual([]);
});
