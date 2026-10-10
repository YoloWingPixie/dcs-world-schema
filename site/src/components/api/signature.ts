import type { Token } from "@/lib/api/types";

/** Signatures longer than this many characters set one parameter per line. */
export const WRAP_AT = 64;

const OPEN = new Set(["(", "[", "{", "<"]);
const CLOSE = new Set([")", "]", "}", ">"]);

/**
 * Cuts signature tokens into the head (`coord.LLtoLO(`), one part per parameter and the
 * tail (`): Vec2`), only at the outer parentheses and their top-level commas. The parts
 * join back to the same text. Null without a parameter list.
 */
function cutSignature(tokens: Token[]): Token[][] | null {
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
  return done ? parts.filter((p) => p.length) : null;
}

/** The signature cut for one parameter per line; null under two parameters. */
export function splitSignature(tokens: Token[]): Token[][] | null {
  const parts = cutSignature(tokens);
  return parts && parts.length > 3 ? parts : null;
}

/** One parameter of a signature: its name, its `: type` annotation and the `, ` after it. */
export type SigParam = { name: Token[]; type: Token[]; sep: Token[] };

/**
 * The signature as head, parameters (each split into name, annotation and separator) and
 * tail. Everything joins back to the same text. Null without a parameter list.
 */
export function signatureParams(
  tokens: Token[],
): { head: Token[]; params: SigParam[]; tail: Token[] } | null {
  const parts = cutSignature(tokens);
  if (!parts || parts.length < 2) return null;
  const head = parts[0] ?? [];
  const tail = parts[parts.length - 1] ?? [];
  const params = parts.slice(1, -1).map((part): SigParam => {
    const out: SigParam = { name: [], type: [], sep: [] };
    let inType = false;
    part.forEach((t, i) => {
      if (typeof t !== "string") {
        (inType ? out.type : out.name).push(t);
        return;
      }
      let text = t;
      let sep = "";
      if (i === part.length - 1) {
        const m = /,\s*$/.exec(text);
        if (m) {
          sep = m[0];
          text = text.slice(0, m.index);
        }
      }
      if (!inType) {
        const colon = text.indexOf(":");
        if (colon >= 0) {
          if (colon) out.name.push(text.slice(0, colon));
          inType = true;
          text = text.slice(colon);
        } else {
          if (text) out.name.push(text);
          text = "";
        }
      }
      if (text) out.type.push(text);
      if (sep) out.sep.push(sep);
    });
    return out;
  });
  return { head, params, tail };
}

/** The plain text of display tokens. */
export const tokenText = (tokens: Token[]) =>
  tokens.map((t) => (typeof t === "string" ? t : t.r)).join("");

/**
 * A signature's tail (`): Unit?`) as the closing parenthesis, the `: ` before the return
 * type and the return type itself (empty when the function returns nothing).
 */
export function splitReturn(tail: Token[]): { close: Token[]; colon: string; returns: Token[] } {
  const [first, ...rest] = tail;
  if (typeof first !== "string" || !first.startsWith(")")) {
    return { close: tail, colon: "", returns: [] };
  }
  const after = first.slice(1);
  const colon = /^:\s*/.exec(after)?.[0] ?? "";
  if (!colon) return { close: tail, colon: "", returns: [] };
  const lead = after.slice(colon.length);
  return { close: [")"], colon, returns: [...(lead ? [lead] : []), ...rest] };
}
