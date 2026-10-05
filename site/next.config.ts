import type { NextConfig } from "next";

// Set SITE_BASE_PATH when the site is served under a subpath (Cloudflare Pages serves it at /).
const basePath = process.env.SITE_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  output: "export",
  basePath,
  trailingSlash: true,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
  poweredByHeader: false,
};

export default nextConfig;
