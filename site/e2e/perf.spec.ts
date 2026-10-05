import { mkdirSync, writeFileSync } from "node:fs";
import { type Browser, expect, type Page, test } from "@playwright/test";

// Cold loads over a throttled 4G link (~9 Mbps down, ~85 ms RTT), each in a fresh context.
// Budgets apply to the deployed layout (SITE_DB_MODE=chunked: parts, no Range support).
// A cold record page moves ~1.3 MB (wasm ~440 KB, startup parts ~420 KB, JS, fonts), so
// ~1.2 s is the floor at 9 Mbps; measured ~2.0 s and 15-17 part requests.
const BUDGET_MS = 2500;
const BUDGET_PARTS = 18;
const chunked = process.env.SITE_DB_MODE === "chunked";
const PROFILE = {
  offline: false,
  latency: 85,
  downloadThroughput: (9_000_000 / 8) | 0,
  uploadThroughput: (3_000_000 / 8) | 0,
};

type Measure = {
  page: string;
  ms: number;
  requests: number;
  bytes: number;
  dbRequests: number;
  dbBytes: number;
};

const results: Measure[] = [];
const isDb = (url: string) => /\/data\/db\/|\/data\/reference\.sqlite/.test(url);

async function cold(
  browser: Browser,
  name: string,
  url: string,
  ready: (page: Page) => Promise<void>,
  act?: (page: Page) => Promise<void>,
): Promise<Measure> {
  const context = await browser.newContext();
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: false });
  await cdp.send("Network.emulateNetworkConditions", PROFILE);
  // Requests the network served (HTTP cache hits transfer nothing), workers included.
  const m: Measure = { page: name, ms: 0, requests: 0, bytes: 0, dbRequests: 0, dbBytes: 0 };
  const pending: Promise<void>[] = [];
  context.on("requestfinished", (r) => {
    pending.push(
      r.sizes().then(
        (s) => {
          const bytes = s.responseHeadersSize + s.responseBodySize;
          if (r.url().startsWith("data:") || bytes <= 0) return;
          m.requests++;
          m.bytes += bytes;
          if (isDb(r.url())) {
            m.dbRequests++;
            m.dbBytes += bytes;
          }
        },
        () => undefined,
      ),
    );
  });
  const start = Date.now();
  await page.goto(url);
  if (act) await act(page);
  await ready(page);
  m.ms = Date.now() - start;
  // Worker requests report through the page's network domain; let stragglers land.
  await page.waitForTimeout(250);
  await Promise.all(pending);
  await context.close();
  results.push(m);
  return m;
}

const record = (title: string) => async (page: Page) => {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title, { timeout: 20_000 });
  await expect(page.locator("#overview")).toBeVisible({ timeout: 20_000 });
};

test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

test("cold loads stay within the speed budget", async ({ browser }) => {
  await cold(browser, "home", "/", async (page) => {
    await expect(page.locator(".series-card-count").first()).toBeVisible({ timeout: 20_000 });
  });
  const weapon = await cold(browser, "record AIM_120C", "/weapons/AIM_120C/", record("AIM-120C"));
  const aircraft = await cold(
    browser,
    "record F-16C_50",
    "/aircraft/F-16C_50/",
    record("F-16CM bl.50"),
  );
  await cold(browser, "browse weapons", "/weapons/", async (page) => {
    await expect(page.locator("table.table tbody tr").first()).toBeVisible({ timeout: 20_000 });
  });
  await cold(browser, "api Unit", "/api/Unit/", async (page) => {
    await expect(page.getByRole("heading", { level: 1, name: "Unit" })).toBeVisible({
      timeout: 20_000,
    });
  });
  await cold(browser, "search amraam", "/search/?q=amraam", async (page) => {
    await expect(page.getByRole("option", { name: /^AIM-120C\b/ }).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  const mode = chunked ? "chunked" : "full";
  const table = results
    .map(
      (r) =>
        `${r.page.padEnd(18)} ${String(r.ms).padStart(5)} ms  ${String(r.requests).padStart(3)} req ${(r.bytes / 1024).toFixed(0).padStart(6)} KiB  db ${String(r.dbRequests).padStart(3)} req ${(r.dbBytes / 1024).toFixed(0).padStart(6)} KiB`,
    )
    .join("\n");
  console.log(`\nCold loads (${mode}, 9 Mbps / 85 ms):\n${table}`);
  mkdirSync("test-results", { recursive: true });
  writeFileSync(`test-results/perf-${mode}.json`, `${JSON.stringify(results, null, 2)}\n`);

  if (chunked) {
    for (const r of [weapon, aircraft]) {
      expect.soft(r.ms, `${r.page}: time to content`).toBeLessThanOrEqual(BUDGET_MS);
      expect
        .soft(r.dbRequests, `${r.page}: database part requests`)
        .toBeLessThanOrEqual(BUDGET_PARTS);
    }
  }
});
