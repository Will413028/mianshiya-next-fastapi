import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("首頁、題庫、單題、Markdown 題解與響應式畫面", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /把每一道題，\s*變成你說得清楚的知識。/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /CHAPTER 01/ })).toBeVisible();
  const bankLink = page.getByRole("link", { name: /CHAPTER 01/ });
  const bankTitle = await bankLink.locator("h3").textContent();
  await bankLink.click();
  await expect(page).toHaveURL(/\/bank\/[1-9][0-9]*$/);
  await expect(page.getByRole("heading", { level: 1, name: bankTitle!, exact: true })).toBeVisible();
  const link = page.locator(".list-item h3").first();
  await expect(link).toBeVisible();
  const title = await link.textContent();
  await link.click();
  await expect(page).toHaveURL(/\/bank\/[1-9][0-9]*\/question\/[1-9][0-9]*$/);
  await expect(page.getByRole("heading", { level: 1, name: title! })).toBeVisible();
  await page.getByRole("button", { name: "完成思考，查看題解" }).click();
  await expect(page.getByRole("heading", { name: "參考題解" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "題庫題目導覽" }).getByRole("link", { name: title!, exact: true })).toBeVisible();
  await page.screenshot({ path: "../../reports/question-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../../reports/question-mobile.png", fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test("註冊、個人資料、閱讀活動、面試建立與登出", async ({ page }) => {
  const account = "browser-" + randomUUID().slice(0,8);
  await page.goto("/user/register");
  await page.getByLabel("帳號", { exact: true }).fill(account);
  await page.getByLabel("密碼", { exact: true }).fill("browser-example-password");
  await page.getByLabel("再次輸入密碼").fill("browser-example-password");
  await page.getByRole("button", { name: "註冊並開始學習" }).click();
  await expect(page.getByRole("heading", { name: /的學習空間/ })).toBeVisible();
  await page.getByLabel("姓名", { exact: true }).fill("瀏覽器學習者");
  await page.getByRole("button", { name: "保存資料" }).click();
  await expect(page.getByRole("status")).toContainText("個人資料已保存");
  await page.goto("/banks");
  await page.locator(".card").first().click();
  await page.locator(".list-item h3").first().click();
  await expect(page.getByRole("button", { name: "完成思考，查看題解" })).toBeVisible();
  await page.goto("/user/center");
  await expect(page.getByRole("heading", { name: "閱讀活動 · 1 天" })).toBeVisible();
  await page.goto("/mockInterview/add");
  await page.getByLabel("職位", { exact: true }).fill("FastAPI 工程師");
  await page.getByRole("button", { name: "建立面試" }).click();
  await expect(page.getByRole("heading", { name: "FastAPI 工程師", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "開始面試" })).toBeVisible();
  await page.getByRole("button", { name: "登出", exact: true }).click();
  await expect(page.getByRole("link", { name: "登入 / 註冊" })).toBeVisible();
  await page.goto("/admin/user");
  await expect(page.getByText("需要管理員權限。", { exact: true })).toBeVisible();
});

test("SSR 登入 cookie 傳遞與使用者快取隔離", async ({ browser }) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  const anonymous = await browser.newContext();
  for (const [index, context] of [first, second].entries()) {
    const page = await context.newPage();
    await page.goto("/user/register");
    await page.getByLabel("帳號", { exact: true }).fill("ssr-"+index+"-"+randomUUID().slice(0,8));
    await page.getByLabel("密碼", { exact: true }).fill("browser-example-password");
    await page.getByLabel("再次輸入密碼").fill("browser-example-password");
    await page.getByRole("button", { name: "註冊並開始學習" }).click();
    await expect(page.getByRole("heading", { name: /的學習空間/ })).toBeVisible();
    await page.getByLabel("姓名", { exact: true }).fill("SSR-person-"+index);
    await page.getByRole("button", { name: "保存資料" }).click();
    await expect(page.getByRole("status")).toBeVisible();
  }
  for (const [index, context] of [first, second, anonymous].entries()) {
    const response = await context.request.get("/");
    const html = await response.text();
    if (index < 2) {
      expect(html.includes("SSR-person-"+index)).toBe(true);
      expect(html.includes("SSR-person-"+(1-index))).toBe(false);
    } else {
      expect(html.includes("SSR-person-")).toBe(false);
    }
  }
  await first.close(); await second.close(); await anonymous.close();
});

test("個人資料載入前不可編輯，切換活動年份保留草稿", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/v1/users/me", async route => {
    if (route.request().method() === "GET") await gate;
    await route.continue();
  });
  await page.goto("/user/register");
  await page.getByLabel("帳號", { exact: true }).fill("draft-"+randomUUID().slice(0,8));
  await page.getByLabel("密碼", { exact: true }).fill("browser-example-password");
  await page.getByLabel("再次輸入密碼").fill("browser-example-password");
  await page.getByRole("button", { name: "註冊並開始學習" }).click();
  try {
    await expect(page.getByRole("heading", { name: /的學習空間/ })).toBeVisible();
    await expect(page.getByLabel("姓名", { exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "保存資料", exact: true })).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByLabel("姓名", { exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "保存資料", exact: true })).toBeEnabled();
  await page.getByLabel("姓名", { exact: true }).fill("尚未儲存的草稿");
  const activity = page.waitForResponse(response => response.url().includes("/users/me/activity") && response.ok());
  await page.getByLabel("活動年份").selectOption(String(new Date().getFullYear()-1));
  await activity;
  await expect(page.getByLabel("姓名", { exact: true })).toHaveValue("尚未儲存的草稿");
});
