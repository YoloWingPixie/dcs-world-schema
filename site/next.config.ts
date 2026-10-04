import type { NextConfig } from "next";

// GitHub Pages serves a project site under /<repo>; set SITE_BASE_PATH=/dcs-world-schema there.
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
