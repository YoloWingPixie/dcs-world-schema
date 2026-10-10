/**
 * A small Lua tokenizer for the dump files the "View Lua" drawer shows (the `_G` dump's
 * serialize.lua output: one assignment of a table constructor). It finds what the view
 * colours and leaves the rest (names, operators, punctuation) as gaps between tokens.
 *
 * `__dcs{...}` markers (functions, refs, redactions) are one "marker" token, except an
 * anchor's `value={...}`: only its head (`__dcs{kind="anchor", id=1, value=`) and closing
 * brace are markers, the table it wraps is tokenized as usual.
 */

export type TokenKind = "comment" | "string" | "number" | "key" | "literal" | "marker";

/** Flat token list: kind, start, end (exclusive), three entries per token. */
export type Tokens = { kinds: TokenKind[]; starts: number[]; ends: number[] };

const IDENT_START = /[A-Za-z_]/;
const IDENT = /[A-Za-z0-9_]/;
const DIGIT = /[0-9]/;
const NUMBER = /(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)/y;
const LITERALS = new Set(["true", "false", "nil"]);
const MARKER = "__dcs";

/** End of the `[=*[` long bracket at `i` (index after its close), or -1 if `i` opens none. */
export function longBracketEnd(text: string, i: number): number {
  if (text[i] !== "[") return -1;
  let j = i + 1;
  while (text[j] === "=") j++;
  if (text[j] !== "[") return -1;
  const close = `]${"=".repeat(j - i - 1)}]`;
  const at = text.indexOf(close, j + 1);
  return at < 0 ? text.length : at + close.length;
}

/** End of the quoted string at `i` (index after its quote). */
export function quotedEnd(text: string, i: number): number {
  const q = text[i];
  let j = i + 1;
  while (j < text.length) {
    const c = text[j];
    if (c === "\\") j += 2;
    else if (c === q || c === "\n") return j + 1;
    else j++;
  }
  return text.length;
}

function skipSpace(text: string, i: number): number {
  while (i < text.length && /\s/.test(text[i] as string)) i++;
  return i;
}

/** Whether `i` (after whitespace) is a lone `=` (an assignment, not `==`). */
function assignsAt(text: string, i: number): boolean {
  const j = skipSpace(text, i);
  return text[j] === "=" && text[j + 1] !== "=";
}

/**
 * Where an `__dcs{` marker at `i` stops being dim: after `value=` when its value is a
 * table (an anchor; `wraps` true), else after its closing brace.
 */
function markerHead(text: string, i: number): { end: number; wraps: boolean } {
  let j = i + MARKER.length;
  j = skipSpace(text, j);
  let depth = 0;
  while (j < text.length) {
    const c = text[j] as string;
    if (c === '"' || c === "'") {
      j = quotedEnd(text, j);
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return { end: j + 1, wraps: false };
    } else if (depth === 1 && text.startsWith("value", j) && !IDENT.test(text[j - 1] ?? "")) {
      const eq = skipSpace(text, j + 5);
      if (text[eq] === "=" && text[eq + 1] !== "=") {
        const v = skipSpace(text, eq + 1);
        if (text[v] === "{") return { end: v, wraps: true };
      }
    }
    j++;
  }
  return { end: text.length, wraps: false };
}

export function tokenize(text: string): Tokens {
  const kinds: TokenKind[] = [];
  const starts: number[] = [];
  const ends: number[] = [];
  const push = (kind: TokenKind, start: number, end: number) => {
    const last = kinds.length - 1;
    if (last >= 0 && kinds[last] === kind && ends[last] === start) {
      ends[last] = end;
    } else {
      kinds.push(kind);
      starts.push(start);
      ends.push(end);
    }
  };
  // Brace depth, and the depths of open anchor markers (their `}` is dim too).
  let depth = 0;
  const markers: number[] = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i] as string;
    if (c === "-" && text[i + 1] === "-") {
      const long = longBracketEnd(text, i + 2);
      let end = long;
      if (long < 0) {
        end = text.indexOf("\n", i);
        if (end < 0) end = n;
      }
      push("comment", i, end);
      i = end;
    } else if (c === '"' || c === "'") {
      const end = quotedEnd(text, i);
      // ["name"] = ...: a key.
      let before = i - 1;
      while (before >= 0 && /\s/.test(text[before] as string)) before--;
      const after = skipSpace(text, end);
      const isKey = text[before] === "[" && text[after] === "]" && assignsAt(text, after + 1);
      push(isKey ? "key" : "string", i, end);
      i = end;
    } else if (c === "[" && (text[i + 1] === "[" || text[i + 1] === "=")) {
      const end = longBracketEnd(text, i);
      if (end < 0) i++;
      else {
        push("string", i, end);
        i = end;
      }
    } else if (DIGIT.test(c) || (c === "." && DIGIT.test(text[i + 1] ?? ""))) {
      NUMBER.lastIndex = i;
      const m = NUMBER.exec(text);
      const end = m ? i + m[0].length : i + 1;
      push("number", i, end);
      i = end;
    } else if (IDENT_START.test(c)) {
      let end = i + 1;
      while (end < n && IDENT.test(text[end] as string)) end++;
      const word = text.slice(i, end);
      if (word === MARKER && text[skipSpace(text, end)] === "{") {
        const head = markerHead(text, i);
        push("marker", i, head.end);
        if (head.wraps) {
          depth++;
          markers.push(depth);
        }
        i = head.end;
      } else {
        if (LITERALS.has(word)) push("literal", i, end);
        else if (assignsAt(text, end) && !/[.:]/.test(text[i - 1] ?? "")) push("key", i, end);
        i = end;
      }
    } else if (c === "{") {
      depth++;
      i++;
    } else if (c === "}") {
      if (markers.length && markers[markers.length - 1] === depth) {
        markers.pop();
        push("marker", i, i + 1);
      }
      depth--;
      i++;
    } else {
      i++;
    }
  }
  return { kinds, starts, ends };
}
