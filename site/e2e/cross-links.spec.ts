import { expect, test } from "@playwright/test";

// The reference data and the Lua API as one book: the API is a chapter of the contents,
// records link to the API where the API names them, and API pages link back.

test("the contents list the Lua API as a chapter", async ({ page }) => {
  await page.goto("/");
  const chapter = page.locator(".contents-chapter").filter({ has: page.locator("#group-api") });
  await expect(chapter.getByRole("heading", { name: /Lua scripting API/i })).toBeVisible();
  const classes = chapter.getByRole("link", { name: /Classes/ });
  await expect(classes).toHaveAttribute("href", /\/api\/#classes$/);
  await expect(classes.locator(".contents-count")).toHaveText(/^\d+/);
  await classes.click();
  await expect(page).toHaveURL(/\/api\/#classes$/);
  await expect(page.locator("#classes")).toBeInViewport();
});

test("a unit record names its Lua class, type name and enum value", async ({ page }) => {
  await page.goto("/aircraft/F-16C_50/");
  const block = page.locator("#scripting");
  await expect(block.locator('[data-scripting="class"]')).toContainText("Unit");
  await expect(block.locator('[data-scripting="member"]')).toContainText('"F-16C_50"');
  await expect(
    block.locator('[data-scripting="member"]').getByRole("link", { name: "Unit:getTypeName()" }),
  ).toHaveAttribute("href", /\/api\/Unit\/#getTypeName$/);
  await expect(page.getByRole("navigation", { name: "On this page" })).toContainText("Scripting");

  // The enum link lands on the value's row.
  await block.getByRole("link", { name: 'DcsId.AircraftType["F-16CM bl.50"]' }).click();
  await expect(page).toHaveURL(/\/api\/types\/DcsId\/AircraftType\/#v-F-16CM%2520bl\.50$/);
  const row = page.locator('[id="v-F-16CM%20bl.50"]');
  await expect(row).toBeInViewport();
  await expect(row.getByRole("link")).toHaveAttribute("href", /\/aircraft\/F-16C_50\/$/);
});

test("an airbase record links to the Airbase class and its theatre's enums", async ({ page }) => {
  await page.goto("/airbases/Caucasus.22/");
  const block = page.locator("#scripting");
  await expect(block.locator('[data-scripting="field-airdromeId"]')).toContainText("22");
  await expect(
    block.getByRole("link", { name: "DcsId.Theatre.Caucasus.AirdromeId.Batumi" }),
  ).toBeVisible();
  await expect(block.getByRole("link", { name: "Airbase.Category.AIRDROME" })).toBeVisible();
});

test("API pages link back to the data and sit under the reference", async ({ page }) => {
  await page.goto("/api/Airbase/");
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(crumbs.getByRole("link").first()).toHaveText("Reference");
  await page.locator(".api-data").getByRole("link", { name: "Airbases" }).click();
  await expect(page).toHaveURL(/\/airbases\/$/);

  // A fixed enum's values link to the records holding them.
  await page.goto("/api/types/Unit/SensorType/");
  const radar = page.locator('[id="v-RADAR"]');
  await expect(radar.getByRole("link")).toHaveAttribute(
    "href",
    /\/sensors\/\?f\.categoryName=SENSOR_RADAR$/,
  );
  await radar.getByRole("link").click();
  await expect(page).toHaveURL(/\/sensors\/\?f\.categoryName=SENSOR_RADAR$/);
  await expect(page.locator("table.table tbody tr").first()).toContainText(/./);
});
