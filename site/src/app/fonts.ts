import { preload } from "react-dom";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

// The faces the first screen needs: headings (Archivo 700) and body text (Source Serif 4
// 400). Same files as the latin-*.css @font-face rules in layout.tsx, so the bundler gives
// them the same hashed URLs.
const ABOVE_THE_FOLD = [
  new URL(
    "../../node_modules/@fontsource/archivo/files/archivo-latin-700-normal.woff2",
    import.meta.url,
  ),
  new URL(
    "../../node_modules/@fontsource/source-serif-4/files/source-serif-4-latin-400-normal.woff2",
    import.meta.url,
  ),
];

/** Adds <link rel="preload"> for the above-the-fold fonts (call while rendering). */
export function preloadFonts() {
  for (const url of ABOVE_THE_FOLD) {
    const path = url.pathname.startsWith(`${BASE_PATH}/`)
      ? url.pathname
      : `${BASE_PATH}${url.pathname}`;
    preload(path, { as: "font", type: "font/woff2", crossOrigin: "anonymous" });
  }
}
