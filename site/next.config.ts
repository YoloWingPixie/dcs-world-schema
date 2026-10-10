import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import type { NextConfig } from "next";

// Set SITE_BASE_PATH when the site is served under a subpath (Cloudflare Pages serves it at /).
const basePath = process.env.SITE_BASE_PATH ?? "";

// Versions the worker and wasm URLs (lib/db/boot.ts), so they can be cached for good.
const sqliteRev = (() => {
  const hash = createHash("sha256");
  for (const f of ["public/sqlite/sqlite.worker.js", "public/sqlite/sql-wasm.wasm"]) {
    if (existsSync(f)) hash.update(readFileSync(f));
  }
  return hash.digest("hex").slice(0, 12);
})();

const nextConfig: NextConfig = {
  output: "export",
  basePath,
  trailingSlash: true,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BASE_PATH: basePath, NEXT_PUBLIC_SQLITE_REV: sqliteRev },
  poweredByHeader: false,
};

export default nextConfig;
