import { expect, test } from "@playwright/test";

test("mvp shell exposes the browser review workflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Cyber Interview Agent", exact: true })).toBeVisible();

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
