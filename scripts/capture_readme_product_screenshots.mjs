#!/usr/bin/env node

import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = resolve(repositoryRoot, "assets/readme");
const baseUrl = process.env.README_DEMO_URL ?? "http://127.0.0.1:5174";
const browserExecutable = process.env.README_DEMO_BROWSER;
const targetId = process.env.README_DEMO_TARGET_ID;
const projectId = process.env.README_DEMO_PROJECT_ID;

if (!targetId || !projectId) {
  throw new Error(
    "README_DEMO_TARGET_ID and README_DEMO_PROJECT_ID are required",
  );
}

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(browserExecutable ? { executablePath: browserExecutable } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1366, height: 768 },
  deviceScaleFactor: 1,
  colorScheme: "light",
});
const page = await context.newPage();

try {
  await page.goto(`${baseUrl}/review`, { waitUntil: "networkidle" });
  await page.getByText("题库整理", { exact: true }).first().click();
  await page
    .getByText("后端与 Agent 面试随手记", { exact: true })
    .click();
  await page
    .getByText("4 / 4", { exact: true })
    .waitFor({ state: "visible" });
  await page.screenshot({
    path: resolve(outputDirectory, "04-product-question-curation.jpg"),
    type: "jpeg",
    quality: 92,
  });

  const deepDiveUrl = new URL("/targets", baseUrl);
  deepDiveUrl.searchParams.set("tab", "deep-dive");
  deepDiveUrl.searchParams.set("target", targetId);
  deepDiveUrl.searchParams.set("project", projectId);
  await page.goto(deepDiveUrl.toString(), { waitUntil: "networkidle" });
  await page
    .getByText("工单分类与知识检索助手", { exact: true })
    .first()
    .waitFor({ state: "visible" });
  await page.locator("#agent-workspace-aside").waitFor({ state: "visible" });
  await page.screenshot({
    path: resolve(outputDirectory, "06-product-agent-runtime.jpg"),
    type: "jpeg",
    quality: 92,
  });
} finally {
  await browser.close();
}
