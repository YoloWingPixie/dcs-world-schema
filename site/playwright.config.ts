import { defineConfig } from "@playwright/test";

const port = Number(process.env.SITE_PORT ?? 3211);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["line"]],
  use: { baseURL: `http://127.0.0.1:${port}` },
  // Serves the static export; run `pnpm build` first.
  webServer: {
    command: `node scripts/serve-out.mjs ${port}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: true,
  },
});
