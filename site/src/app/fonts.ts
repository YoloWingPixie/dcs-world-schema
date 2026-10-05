import { preload } from "react-dom";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

// The faces the first screen needs: headings (Chakra Petch 600/700) and body text (Barlow
// 400). Same files as the latin-*.css @font-face rules in layout.tsx, so the bundler gives
// them the same hashed URLs.
const ABOVE_THE_FOLD = [
  new URL(
    "../../node_modules/@fontsource/chakra-petch/files/chakra-petch-latin-600-normal.woff2",
    import.meta.url,
  ),
  new URL(
    "../../node_modules/@fontsource/chakra-petch/files/chakra-petch-latin-700-normal.woff2",
    import.meta.url,
  ),
  new URL(
    "../../node_modules/@fontsource/barlow/files/barlow-latin-400-normal.woff2",
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
