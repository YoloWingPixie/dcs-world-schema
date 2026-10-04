import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/chakra-petch/600.css";
import "@fontsource/chakra-petch/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
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
import { UNITS_BOOTSTRAP } from "@/lib/units";

export const metadata: Metadata = {
  title: { default: "DCS World Reference", template: "%s · DCS World Reference" },
  description:
    "Aircraft, weapons, sensors, airbases and every other record DCS World ships, field by field.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#edf1f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0d1316" },
  ],
};

// Applies a stored theme before first paint; without one, the system preference rules.
const themeScript = `try{var t=localStorage.getItem("dcs-ref:theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}${UNITS_BOOTSTRAP}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* biome-ignore lint/security/noDangerouslySetInnerHtml: static theme bootstrap */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
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
