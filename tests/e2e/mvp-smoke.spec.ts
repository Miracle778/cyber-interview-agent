import { expect, test } from "@playwright/test";

test("mvp shell exposes the browser review workflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Cyber Interview Agent", exact: true })).toBeVisible();
  await expect(page.getByText(/正在检查后端连接|后端已连接|后端未连接，请确认 FastAPI 服务已启动/)).toBeVisible();
  await expect(page.getByText("Workspace：待初始化")).toBeVisible();
  await expect(page.getByText("题库草稿：待生成")).toBeVisible();
  await expect(page.getByText("复习报告：待生成")).toBeVisible();
  await expect(page.getByText("Vault 索引：待扫描")).toBeVisible();

  const sectionHeadings = await page.getByRole("heading", { level: 2 }).allTextContents();
  expect(sectionHeadings.slice(0, 3)).toEqual(["设置", "知识文档", "复习"]);

  await expect(page.getByRole("button", { name: "测试连接" })).toBeVisible();
  await expect(page.getByRole("button", { name: "初始化工作区" })).toBeVisible();
  await expect(page.getByRole("button", { name: "上传资料" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新扫描 Vault" })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送回答" })).toBeVisible();

  await expect(page.getByText("请先初始化工作区")).toBeVisible();
  await expect(page.getByText("请先上传资料生成题库草稿")).toBeVisible();
});
