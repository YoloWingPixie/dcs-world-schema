import { expect, test } from "@playwright/test";

test("API home -> Unit -> getByName anchor", async ({ page }) => {
  await page.goto("/api/");
  await expect(page.getByRole("heading", { level: 1, name: "DCS World Lua API" })).toBeVisible();
  await page
    .locator("#mission")
    .getByRole("link", { name: /^Unit\b/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/api\/Unit\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Unit" })).toBeVisible();

  await page
    .getByRole("navigation", { name: "On this page" })
    .getByRole("link", { name: "getByName", exact: true })
    .click();
  await expect(page).toHaveURL(/\/api\/Unit\/#getByName$/);
  const entry = page.locator("article#getByName");
  await expect(entry).toBeInViewport();
  await expect(entry.locator(".api-sig")).toHaveText("Unit.getByName(name: string): Unit?");
  // On screen the heading drops the owner and the parameter types the list below gives.
  await expect(entry.locator(".api-sig-name")).toBeVisible();
  await expect(entry.locator(".api-sig-owner")).toHaveCSS("position", "absolute");
  await expect(entry.locator(".api-sig-ptype")).toHaveCSS("position", "absolute");
  // The return type shows after a RETURNS label (CSS content, silent to screen readers);
  // the Lua `: ` before it stays in the text, hidden.
  const returns = entry.locator(".api-sig-returns");
  await expect(returns).toBeVisible();
  await expect(returns).toHaveText("Unit?");
  expect(await returns.evaluate((el) => getComputedStyle(el, "::before").content)).toContain(
    "Returns",
  );
  await expect(entry.locator(".api-sig-rcolon")).toHaveCSS("position", "absolute");
  // Every type name links to its page.
  await expect(entry.locator(".api-sig a", { hasText: "Unit" })).toHaveAttribute(
    "href",
    /\/api\/Unit\/$/,
  );
  // The overlay renders.
  await expect(entry.getByRole("complementary", { name: "Notes" })).toBeVisible();
  // Inherited methods link to their origin.
  await expect(page.locator("#inherited a", { hasText: "Unit:isExist" })).toHaveAttribute(
    "href",
    /\/api\/Object\/#isExist$/,
  );
});

test("palette finds trigger.action.outText", async ({ page }) => {
  await page.goto("/api/");
  await page.keyboard.press("Control+k");
  const input = page.getByRole("combobox").first();
  await input.fill("outText");
  const option = page.getByRole("option", { name: /trigger\.action\.outText/ }).first();
  await expect(option).toBeVisible();
  await option.click();
  await expect(page).toHaveURL(/\/api\/trigger\/action\/#outText$/);
  await expect(page.locator("article#outText .api-sig")).toContainText(
    "trigger.action.outText(text: string, displayTime: number, clearview?: boolean)",
  );
});

test("large enum is filterable and links to reference records", async ({ page }) => {
  await page.goto("/api/types/DcsId/WeaponType/");
  const filter = page.getByRole("searchbox", { name: /Filter DcsId.WeaponType values/ });
  await filter.fill("AIM_120C");
  const rows = page.locator("#values tbody tr");
  await expect(rows.first()).toContainText("AIM_120C");
  await expect(rows.first().getByRole("link")).toHaveAttribute("href", /\/weapons\//);
});

test("deep links and reloads render from the database", async ({ page }) => {
  await page.goto("/api/types/DcsTask/Task/Orbit/");
  await expect(page.getByRole("heading", { level: 1, name: "DcsTask.Task.Orbit" })).toBeVisible();
  await page.getByRole("link", { name: "DcsTask.Task.OrbitParams" }).first().click();
  await expect(page).toHaveURL(/\/api\/types\/DcsTask\/Task\/OrbitParams\/$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "DcsTask.Task.OrbitParams" }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "DcsTask.Task.Orbit" })).toBeVisible();

  await page.goto("/api/Object/#isExist");
  await expect(page.locator("article#isExist")).toBeInViewport();
  await page.reload();
  await expect(page.locator("article#isExist")).toBeInViewport();

  await page.goto("/api/");
  await page.getByRole("button", { name: "Hooks", exact: true }).click();
  await expect(page.locator("#mission")).toHaveCount(0);
  await page
    .locator("#hooks")
    .getByRole("link", { name: /^DCS\b/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/api\/hooks\/DCS\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "DCS", exact: true })).toBeVisible();
  await page.goto("/api/NoSuchGlobal/");
  await expect(page.getByRole("heading", { name: "No such API page" })).toBeVisible();
});
