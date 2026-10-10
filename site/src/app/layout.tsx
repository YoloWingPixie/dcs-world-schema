// Latin subset only (other scripts fall back to system fonts); each sets font-display: swap.
import "@fontsource/source-serif-4/latin-400.css";
import "@fontsource/source-serif-4/latin-400-italic.css";
import "@fontsource/source-serif-4/latin-600.css";
import "@fontsource/archivo/latin-500.css";
import "@fontsource/archivo/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./globals.css";
import "../styles/record.css";
import "../styles/browse.css";
import "../styles/compare.css";
import "../styles/search.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { CommandPalette } from "@/components/command-palette";
import { FieldMenu } from "@/components/field-menu";
import { SiteHeader } from "@/components/header";
import { DataVersion } from "@/components/series-directory";
import { Toaster } from "@/components/toast";
import { bootScript, CONFIG_URL, WASM_URL, WORKER_URL } from "@/lib/db/boot";
import { UNITS_BOOTSTRAP } from "@/lib/units";
import { preloadFonts } from "./fonts";

export const metadata: Metadata = {
  title: { default: "DCS World Reference", template: "%s · DCS World Reference" },
  description: "DCS World data reference and Lua API.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#161616" },
  ],
};

// Applies a stored theme before first paint; without one, the system preference rules.
const themeScript = `try{var t=localStorage.getItem("dcs-ref:theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}${UNITS_BOOTSTRAP}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  preloadFonts();
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* biome-ignore lint/security/noDangerouslySetInnerHtml: static theme bootstrap */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <link rel="preload" href={CONFIG_URL} as="fetch" crossOrigin="anonymous" />
        <link rel="preload" href={WASM_URL} as="fetch" crossOrigin="anonymous" />
        <link rel="preload" href={WORKER_URL} as="script" />
        <link
          rel="preload"
          href={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/overlays/reference.json`}
          as="fetch"
          crossOrigin="anonymous"
        />
        {/* biome-ignore lint/security/noDangerouslySetInnerHtml: static database prefetch */}
        <script dangerouslySetInnerHTML={{ __html: bootScript() }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="site-footer-inner">
            <DataVersion variant="footer" />
          </div>
        </footer>
        <CommandPalette />
        <FieldMenu />
        <Toaster />
      </body>
    </html>
  );
}
