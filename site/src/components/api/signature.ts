import type { Token } from "@/lib/api/types";

/** Signatures longer than this many characters set one parameter per line. */
export const WRAP_AT = 64;

const OPEN = new Set(["(", "[", "{", "<"]);
const CLOSE = new Set([")", "]", "}", ">"]);

/**
 * Splits signature tokens into the head (`coord.LLtoLO(`), one part per parameter and the
 * tail (`): Vec2`), cutting only at the outer parentheses and their top-level commas. The
 * parts join back to the same text. Null when there is nothing to split.
 */
export function splitSignature(tokens: Token[]): Token[][] | null {
  const parts: Token[][] = [[]];
  let depth = 0;
  let done = false;
  const push = (t: Token) => {
    if (t !== "") parts[parts.length - 1]?.push(t);
  };
  for (const t of tokens) {
    if (typeof t !== "string" || done) {
      push(t);
      continue;
    }
    let start = 0;
    for (let i = 0; i < t.length; i++) {
      const c = t[i] ?? "";
      if (c === ">" && t[i - 1] === "-") continue;
      if (OPEN.has(c)) {
        depth++;
        if (depth === 1 && !done) {
          push(t.slice(start, i + 1));
          parts.push([]);
          start = i + 1;
        }
      } else if (CLOSE.has(c)) {
        depth--;
        if (depth === 0 && !done) {
          push(t.slice(start, i));
          parts.push([]);
          start = i;
          done = true;
          break;
        }
      } else if (c === "," && depth === 1) {
        const end = t[i + 1] === " " ? i + 2 : i + 1;
        push(t.slice(start, end));
        parts.push([]);
        start = end;
        i = end - 1;
      }
    }
    push(t.slice(start));
  }
  const filled = parts.filter((p) => p.length);
  return done && filled.length > 3 ? filled : null;
}

/** The plain text of display tokens. */
export const tokenText = (tokens: Token[]) =>
  tokens.map((t) => (typeof t === "string" ? t : t.r)).join("");
