/**
 * Finds the text of a `sourcePath` pointer (`<dump path>#/a/[1]/b`, tools/datamine/dump_paths.py)
 * in a dump file: parses the file's one assignment into a tree of ranges and follows the
 * pointer's keys, through anchors and same-file refs. Where a key is missing (or the path
 * continues in another file) the deepest table reached is returned, marked partial.
 */
import { longBracketEnd, quotedEnd } from "./tokenize";

type Key = string | number | boolean;

type Node =
  | { type: "table"; start: number; end: number; entries: Entry[] }
  | { type: "marker"; start: number; end: number; fields: Entry[] }
  | { type: "scalar"; start: number; end: number; value: Key | null };

type Entry = { key: Key; start: number; node: Node };

export type Located = { start: number; end: number; partial: boolean };

/** One pointer segment's Lua key (dump_paths._parse_segment). */
export function parseSegment(seg: string): Key {
  if (seg.startsWith("[") && seg.endsWith("]") && seg.length > 2) {
    const lit = seg.slice(1, -1);
    if (lit === "true" || lit === "false") return lit === "true";
    if (lit === "inf") return Number.POSITIVE_INFINITY;
    if (lit === "-inf") return Number.NEGATIVE_INFINITY;
    const n = Number(lit);
    if (lit.trim() !== "" && !Number.isNaN(n)) return n;
    throw new Error(`bad pointer segment ${seg}`);
  }
  return seg.replace(/~([012])/g, (_, d: string) => (d === "0" ? "~" : d === "1" ? "/" : "["));
}

/** The keys of a pointer (`/a/[1]`); [] for "" or "/". */
export function parsePointer(pointer: string): Key[] {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) throw new Error(`pointer does not start with /: ${pointer}`);
  return pointer.slice(1).split("/").map(parseSegment);
}

const ESCAPES: Record<string, string> = {
  n: "\n",
  t: "\t",
  r: "\r",
  a: "\x07",
  b: "\b",
  f: "\f",
  v: "\v",
  "\\": "\\",
  '"': '"',
  "'": "'",
  "\n": "\n",
};

function unquote(raw: string): string {
  if (raw.startsWith("[")) {
    const open = raw.indexOf("[", 1) + 1;
    const body = raw.slice(open, raw.length - open);
    return body.startsWith("\n") ? body.slice(1) : body;
  }
  return raw
    .slice(1, -1)
    .replace(/\\(\d{1,3}|.)/gs, (_, e: string) =>
      /^\d/.test(e) ? String.fromCharCode(Number(e)) : (ESCAPES[e] ?? e),
    );
}

class Parser {
  i = 0;
  constructor(readonly text: string) {}

  space() {
    const t = this.text;
    for (;;) {
      while (this.i < t.length && /\s/.test(t[this.i] as string)) this.i++;
      if (t.startsWith("--", this.i)) {
        const long = longBracketEnd(t, this.i + 2);
        if (long >= 0) this.i = long;
        else {
          const nl = t.indexOf("\n", this.i);
          this.i = nl < 0 ? t.length : nl;
        }
      } else return;
    }
  }

  name(): string | null {
    const m = /[A-Za-z_][A-Za-z0-9_]*/y;
    m.lastIndex = this.i;
    const hit = m.exec(this.text);
    if (!hit) return null;
    this.i += hit[0].length;
    return hit[0];
  }

  value(): Node {
    this.space();
    const t = this.text;
    const start = this.i;
    const c = t[start];
    if (c === "{") return this.table(start);
    if (c === '"' || c === "'") {
      this.i = quotedEnd(t, start);
      return { type: "scalar", start, end: this.i, value: unquote(t.slice(start, this.i)) };
    }
    if (c === "[") {
      const end = longBracketEnd(t, start);
      if (end > 0) {
        this.i = end;
        return { type: "scalar", start, end, value: unquote(t.slice(start, end)) };
      }
    }
    const num = /-?\s*(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)/y;
    num.lastIndex = start;
    const hit = num.exec(t);
    if (hit) {
      this.i += hit[0].length;
      return { type: "scalar", start, end: this.i, value: Number(hit[0].replace(/\s/g, "")) };
    }
    const word = this.name();
    if (word === "__dcs") {
      this.space();
      const inner = this.table(this.i);
      return { type: "marker", start, end: inner.end, fields: inner.entries };
    }
    if (word === "true" || word === "false") {
      return { type: "scalar", start, end: this.i, value: word === "true" };
    }
    if (word === null) this.i++;
    return { type: "scalar", start, end: this.i, value: null };
  }

  table(start: number): Node & { type: "table" } {
    const t = this.text;
    this.i = start + 1;
    const entries: Entry[] = [];
    let index = 1;
    for (;;) {
      this.space();
      if (this.i >= t.length) break;
      if (t[this.i] === "}") {
        this.i++;
        break;
      }
      const at = this.i;
      if (t[at] === "[" && longBracketEnd(t, at) < 0) {
        this.i++;
        const k = this.value();
        this.space();
        if (t[this.i] === "]") this.i++;
        this.space();
        if (t[this.i] === "=") this.i++;
        const v = this.value();
        if (k.type === "scalar" && k.value !== null)
          entries.push({ key: k.value, start: at, node: v });
        else if (k.type === "marker") {
          // [__dcs{kind="number", value="inf"}] = ...
          const val = k.fields.find((f) => f.key === "value")?.node;
          const name = val?.type === "scalar" ? val.value : null;
          const key =
            name === "inf"
              ? Number.POSITIVE_INFINITY
              : name === "-inf"
                ? Number.NEGATIVE_INFINITY
                : null;
          if (key !== null) entries.push({ key, start: at, node: v });
        }
      } else {
        const word = /[A-Za-z_][A-Za-z0-9_]*\s*=(?!=)/y;
        word.lastIndex = at;
        const hit = word.exec(t);
        if (hit) {
          this.i = at + hit[0].length;
          const key = hit[0].replace(/\s*=$/, "");
          entries.push({ key, start: at, node: this.value() });
        } else {
          const v = this.value();
          entries.push({ key: index++, start: at, node: v });
        }
      }
      this.space();
      if (t[this.i] === "," || t[this.i] === ";") this.i++;
      else if (t[this.i] !== "}" && this.i === at) this.i++;
    }
    return { type: "table", start, end: this.i, entries };
  }

  /** The value of the file's assignment (`_G["a"]["b"] = <value>`). */
  file(): Node | null {
    const t = this.text;
    let depth = 0;
    while (this.i < t.length) {
      const c = t[this.i];
      if (c === '"' || c === "'") this.i = quotedEnd(t, this.i);
      else if (c === "[") {
        depth++;
        this.i++;
      } else if (c === "]") {
        depth--;
        this.i++;
      } else if (c === "=" && depth === 0) {
        this.i++;
        return this.value();
      } else this.i++;
    }
    return null;
  }
}

const sameKey = (a: Key, b: Key) => typeof a === typeof b && a === b;

function field(node: Node & { type: "marker" }, name: string): Node | undefined {
  return node.fields.find((f) => f.key === name)?.node;
}

function anchorsOf(root: Node): Map<Key, Node> {
  const out = new Map<Key, Node>();
  const stack: Node[] = [root];
  while (stack.length) {
    const n = stack.pop() as Node;
    if (n.type === "marker") {
      const kind = field(n, "kind");
      const id = field(n, "id");
      const value = field(n, "value");
      if (kind?.type === "scalar" && kind.value === "anchor" && id?.type === "scalar" && value) {
        if (id.value !== null) out.set(id.value, value);
      }
      for (const f of n.fields) stack.push(f.node);
    } else if (n.type === "table") {
      for (const e of n.entries) stack.push(e.node);
    }
  }
  return out;
}

/** The range of `pointer` (`/a/[1]`) in the dump file `text`; null when it has no value. */
export function locate(text: string, pointer: string): Located | null {
  let keys: Key[];
  try {
    keys = parsePointer(pointer);
  } catch {
    return null;
  }
  const root = new Parser(text).file();
  if (!root) return null;
  let anchors: Map<Key, Node> | null = null;
  let node: Node = root;
  let at = { start: root.start, end: root.end };
  for (const key of keys) {
    // Unwrap anchors and same-file refs.
    for (let hops = 0; node.type === "marker" && hops < 64; hops++) {
      const kind = field(node, "kind");
      const kindName = kind?.type === "scalar" ? kind.value : null;
      if (kindName === "anchor") {
        const value = field(node, "value");
        if (!value) break;
        node = value;
      } else if (kindName === "ref") {
        anchors ??= anchorsOf(root);
        const id = field(node, "id");
        const target = id?.type === "scalar" && id.value !== null ? anchors.get(id.value) : null;
        if (!target) break;
        node = target;
      } else break;
    }
    if (node.type !== "table") return { ...at, partial: true };
    const entry: Entry | undefined = node.entries.find((e) => sameKey(e.key, key));
    if (!entry) return { ...at, partial: true };
    node = entry.node;
    at = { start: entry.start, end: entry.node.end };
  }
  return { ...at, partial: false };
}
