import { expect, test } from "@playwright/test";

test("product shell exposes routed interview workflows", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/review$/);
  await expect(page.getByRole("heading", { level: 1, name: "复习" })).toBeVisible();
  await expect(page.getByText(/正在检查后端连接|后端已连接|后端未连接，请确认 FastAPI 服务已启动/)).toBeVisible();
  await expect(
    page.getByLabel("运行状态").locator(".status-chip").filter({ hasText: "Workspace：" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "发送回答" })).toBeVisible();
  await expect(page.getByText("请先上传资料生成题库草稿")).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "主导航" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link", { name: "复习" })).toHaveAttribute("aria-current", "page");

  await navigation.getByRole("link", { name: "知识库" }).click();
  await expect(page).toHaveURL(/\/knowledge$/);
  await expect(page.getByRole("heading", { level: 1, name: "知识库" })).toBeVisible();
  await expect(page.getByRole("button", { name: "上传资料" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新扫描 Vault" })).toBeVisible();

  await navigation.getByRole("link", { name: "设置" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { level: 1, name: "设置" })).toBeVisible();
  await expect(page.getByRole("button", { name: "初始化工作区" })).toBeVisible();
});
