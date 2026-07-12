import { expect, test } from "@playwright/test";

test("settings page keeps configuration progressive and responsive", async ({ page, request }) => {
  const browserMessages: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") browserMessages.push(message.text());
  });

  const workspaceResponse = await request.post("http://127.0.0.1:8017/api/settings/workspaces", {
    data: { rootPath: "/private/tmp/cyber-settings-e2e-workspace" },
  });
  expect(workspaceResponse.ok()).toBeTruthy();

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "配置概览" })).toBeVisible();
  await expect(page.getByText("Provider 管理")).toHaveCount(0);

  await page.getByRole("button", { name: "模型服务" }).click();
  await expect(page.getByRole("button", { name: "添加 Provider" })).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "添加 Provider" }).click();
  await expect(page.getByRole("button", { name: "添加 Provider" })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByLabel("Provider 名称")).toBeVisible();

  await page.getByRole("button", { name: "运行诊断" }).click();
  await expect(page.getByRole("button", { name: /Agent Runtime/ })).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: /Agent Runtime/ }).click();
  await expect(page.getByRole("button", { name: "运行自检" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "配置概览" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBeFalsy();

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBeFalsy();
  await page.getByRole("button", { name: "配置概览" }).focus();
  expect(browserMessages).toEqual([]);
});
