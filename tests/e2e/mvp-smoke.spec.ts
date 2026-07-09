import { expect, test } from "@playwright/test";

test("mvp shell exposes settings review and knowledge sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Cyber Interview Agent", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "设置", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "复习", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "知识文档", exact: true })).toBeVisible();
});
