import { expect, test } from "@playwright/test";

// At phone width a wide table scrolls inside its own .table-wrap; the page itself never
// scrolls sideways. Each page waits for a part that renders from the loaded data.
const pages: Array<{ path: string; ready: string }> = [
  // Runways are record cards with a nested directions table.
  { path: "/airbases/Caucasus.18/", ready: ".record-card .table-wrap" },
  { path: "/aircraft/F-16C_50/", ready: "#stations" },
  { path: "/weapons/AIM_120C/", ready: ".field" },
  { path: "/ground_vehicles/SA-11%20Buk%20LN%209A310M1/", ready: ".field" },
  { path: "/aircraft/", ready: "main table" },
  { path: "/api/Unit/", ready: "article#getByName" },
];

test.use({ viewport: { width: 375, height: 800 } });

for (const { path, ready } of pages) {
  test(`no horizontal page scroll at 375 px: ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator(ready).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(375);
  });
}
