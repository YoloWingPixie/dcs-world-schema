import { expect, type Page, test } from "@playwright/test";

async function openPalette(page: Page) {
  // The shortcut is bound once the page has hydrated.
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Search the reference" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("palette searches across series, groups results and filters by section", async ({ page }) => {
  await page.goto("/");
  const dialog = await openPalette(page);
  const box = dialog.getByRole("combobox");
  await box.fill("batumi");
  await expect(dialog.getByRole("group", { name: "Airbases" })).toBeVisible();
  await expect(
    dialog.getByRole("group", { name: "Airbases" }).getByRole("option").first(),
  ).toContainText("Batumi");
  await box.fill("sidewinder");
  await expect(dialog.getByRole("group", { name: "Weapons" })).toBeVisible();
  await expect(dialog.getByRole("group", { name: "Stores" })).toBeVisible();
  await dialog.getByRole("button", { name: /^Stores/ }).click();
  await expect(dialog.getByRole("group", { name: "Weapons" })).toHaveCount(0);
  await box.fill("amraam");
  await dialog.getByRole("button", { name: "All", exact: true }).click();
  await dialog
    .getByRole("option", { name: /^AIM-120C\b/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/weapons\/AIM_120C\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-120C");
});

test("aircraft page links to a store, and the store links back", async ({ page }) => {
  await page.goto("/aircraft/F-16C_50/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("F-16CM bl.50");
  const stations = page.locator("#stations");
  await stations.getByRole("link", { name: "AIM-9X Sidewinder IR AAM" }).first().click();
  await expect(page).toHaveURL(/\/stores\/%7B5CE2FF2A[^/]*%7D\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-9X Sidewinder IR AAM");
  const refBy = page.locator("#referenced-by");
  await refBy.getByRole("link", { name: "F-16CM bl.50" }).click();
  await expect(page).toHaveURL(/\/aircraft\/F-16C_50\/$/);
});

test("right-click a field on an aircraft and compare it across aircraft", async ({ page }) => {
  await page.goto("/aircraft/F-16C_50/");
  const field = page.locator('.field[data-field="aero.maxTakeoffKg"]');
  await field.scrollIntoViewIfNeeded();
  await field.click({ button: "right", position: { x: 40, y: 12 } });
  await page.getByRole("menuitem", { name: /Compare Max takeoff across aircraft/ }).click();
  await expect(page).toHaveURL(/\/compare\/\?s=aircraft&f=aero\.maxTakeoffKg&r=F-16C_50/);
  await expect(
    page.getByRole("heading", { name: /All \d+ aircraft with this field/ }),
  ).toBeVisible();
});

test("weapon compare: right-click cx0, add R-27ER, the chart shows two series", async ({
  page,
}) => {
  await page.goto("/weapons/AIM_120C/");
  const cx0 = page.locator('[data-field="flight.aerodynamics.cx0"]');
  await cx0.scrollIntoViewIfNeeded();
  await cx0.click({ button: "right", position: { x: 40, y: 12 } });
  await page.getByRole("menuitem", { name: /Compare Zero-lift drag coefficient/ }).click();
  await expect(page).toHaveURL(/\/compare\/\?s=weapons&f=flight\.aerodynamics\.cx0&r=AIM_120C/);

  const chart = page.locator(".chart svg").first();
  await expect(chart.locator("path[data-series]")).toHaveCount(1);

  const add = page.getByRole("combobox", { name: "Add a weapon to compare" });
  await add.fill("R-27ER");
  await expect(page.getByRole("option", { name: /^R-27ER\b/ }).first()).toBeVisible();
  await add.press("Enter");

  await expect(chart.locator("path[data-series]")).toHaveCount(2);
  await expect(chart.locator('path[data-series="P_27PE"]')).toHaveCount(1);
  await expect(page).toHaveURL(/r=AIM_120C,P_27PE/);
});

test("keyboard: C on a focused field jumps to its comparison", async ({ page }) => {
  await page.goto("/weapons/P_27PE/");
  await page.locator('.field[data-field="massKg"]').first().focus();
  await page.keyboard.press("c");
  await expect(page).toHaveURL(/\/compare\/\?s=weapons&f=massKg&r=P_27PE/);
  await expect(
    page.getByRole("heading", { name: /All \d+ weapons with this field/ }),
  ).toBeVisible();
});

test("units switch: AIM-120C mass and range in imperial, and back", async ({ page }) => {
  await page.goto("/weapons/AIM_120C/");
  const mass = page.locator('.readout[data-field="massKg"] .readout-value');
  const range = page.locator('.readout[data-field="rangeKm"] .readout-value');
  await expect(mass).toHaveText(/161\.48\s*kg/);
  await page.getByRole("button", { name: "Imperial" }).click();
  await expect(mass).toHaveText(/356\s*lb/);
  await expect(range).toHaveText(/32\.9\d?\s*nm/);
  await page.reload();
  await expect(mass).toHaveText(/356\s*lb/);
  await page.getByRole("button", { name: "Metric" }).click();
  await expect(mass).toHaveText(/161\.48\s*kg/);
  await page.goto("/weapons/AIM_120C/?units=imperial");
  await expect(mass).toHaveText(/356\s*lb/);
});

test("deep links and reloads land on the record (the host serves the shell)", async ({ page }) => {
  await page.goto("/weapons/AIM_120C/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-120C");
  await expect(page).toHaveTitle(/AIM-120C/);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-120C");
  await page.goBack().catch(() => {});
  await page.goto("/weapons/NO_SUCH_WEAPON/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("No such weapon");
  await page.goto("/no-such-series/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
});

test("links inside the reference navigate without a reload, and back works", async ({ page }) => {
  await page.goto("/weapons/AIM_120C/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-120C");
  await page.evaluate(() => {
    (window as unknown as { __marker: number }).__marker = 1;
  });
  await page.locator("#referenced-by").getByRole("link", { name: "F-16CM bl.50" }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("F-16CM bl.50");
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(1);
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("AIM-120C");
});

test("airbase and sensor pages render with their links", async ({ page }) => {
  await page.goto("/sensors/AN%2FAPG-68/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("APG-68");
  await expect(
    page.locator("#referenced-by").getByRole("link", { name: "F-16CM bl.50" }).first(),
  ).toBeVisible();
  await page.goto("/airbases/");
  await page.getByRole("searchbox").first().fill("Batumi");
  await page.getByRole("link", { name: "Batumi" }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Batumi");
  await expect(page.locator("#runways")).toBeVisible();
});
