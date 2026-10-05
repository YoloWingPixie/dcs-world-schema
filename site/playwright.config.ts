import { defineConfig } from "@playwright/test";

// SITE_DB_MODE=chunked serves a copy of out/ with the database split as deployed, and
// ignores Range headers like Cloudflare Pages.
const chunked = process.env.SITE_DB_MODE === "chunked";
const port = Number(process.env.SITE_PORT ?? (chunked ? 3212 : 3211));
const root = chunked ? "test-results/site-chunked" : "out";
const prepare = chunked
  ? `node -e "const f=require('fs');f.rmSync('${root}',{recursive:true,force:true});f.cpSync('out','${root}',{recursive:true})" && node scripts/split-sqlite.ts ${root} --mode=chunked && SERVE_NO_RANGES=1 `
  : "";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "test-results/playwright",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["line"]],
  use: { baseURL: `http://127.0.0.1:${port}` },
  // Serves the static export; run `pnpm build` first.
  webServer: {
    command: `${prepare}node scripts/serve-out.mjs ${port} ${root}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: true,
  },
});
