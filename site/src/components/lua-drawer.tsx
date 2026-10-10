"use client";

import "../styles/lua.css";
import {
  memo,
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { lineAt, lineStarts, locateIn, parseLua } from "@/lib/lua/locate";
import {
  fileStem,
  type LuaBlock,
  LuaMissing,
  loadLua,
  shortLabels,
  splitSourcePath,
} from "@/lib/lua/source";
import { type Tokens, tokenize } from "@/lib/lua/tokenize";
import { showToast } from "./toast";

/** Above this many characters the text is shown plain (no token spans). */
export const HIGHLIGHT_LIMIT = 200_000;

const FOCUSABLE =
  'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Props = {
  recordId: string;
  name: string;
  /** Dump paths (`_G/a/b`), record sourcePaths first. */
  files: string[];
  blocks: LuaBlock[];
  /** The open dump path, with `#/pointer` for a block. */
  sourcePath: string;
  onNavigate: (sourcePath: string) => void;
  /** The build lacks the dump file of `path` (404). */
  onMissing: (path: string) => void;
  onClose: () => void;
};

type Loaded = { path: string; text: string } | { path: string; error: string };

const formatSize = (n: number) =>
  n < 1024
    ? `${n} B`
    : n < 1024 * 1024
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1048576).toFixed(2)} MB`;

/** Index of the first token ending after `pos`. */
function firstToken(tokens: Tokens, pos: number) {
  let lo = 0;
  let hi = tokens.ends.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((tokens.ends[mid] as number) <= pos) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** `text[from, to)` as plain text and token spans. */
function renderRange(text: string, tokens: Tokens | null, from: number, to: number): ReactNode[] {
  if (!tokens) return [text.slice(from, to)];
  const out: ReactNode[] = [];
  let at = from;
  for (let t = firstToken(tokens, from); t < tokens.kinds.length; t++) {
    const start = Math.max(tokens.starts[t] as number, from);
    if (start >= to) break;
    const end = Math.min(tokens.ends[t] as number, to);
    if (start > at) out.push(text.slice(at, start));
    out.push(
      <span key={start} className={`lt-${tokens.kinds[t]}`}>
        {text.slice(start, end)}
      </span>,
    );
    at = end;
  }
  if (at < to) out.push(text.slice(at, to));
  return out;
}

const lineNumbers = (count: number) => Array.from({ length: count }, (_, i) => i + 1).join("\n");

/** The gutter and code of one file: rendered once per file, never on a block change. */
const CodeBody = memo(function CodeBody({
  text,
  tokens,
  lines,
}: {
  text: string;
  tokens: Tokens | null;
  lines: number;
}) {
  return (
    <>
      <pre className="lua-gutter" aria-hidden="true">
        {lineNumbers(lines)}
      </pre>
      <pre className="lua-text">
        <code>{renderRange(text, tokens, 0, text.length)}</code>
      </pre>
    </>
  );
});

/** Top padding of the code (px; .lua-text in lua.css). */
const CODE_PAD = 12;

function safeName(s: string) {
  return s.replace(/[\\/:*?"<>|\s]+/g, "_");
}

export default function LuaDrawer({
  recordId,
  name,
  files,
  blocks,
  sourcePath,
  onNavigate,
  onMissing,
  onClose,
}: Props) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLElement>(null);
  const codeRef = useRef<HTMLDivElement>(null);
  const missingRef = useRef(onMissing);
  missingRef.current = onMissing;
  const { path, pointer } = splitSourcePath(sourcePath);
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let live = true;
    loadLua(path).then(
      (text) => live && setLoaded({ path, text }),
      (e: unknown) => {
        if (!live) return;
        if (e instanceof LuaMissing) missingRef.current(path);
        else setLoaded({ path, error: e instanceof Error ? e.message : String(e) });
      },
    );
    return () => {
      live = false;
    };
  }, [path]);

  const current = loaded?.path === path ? loaded : null;
  const text = current && "text" in current ? current.text : null;
  const tokens = useMemo(
    () => (text !== null && text.length <= HIGHLIGHT_LIMIT ? tokenize(text) : null),
    [text],
  );
  // Once per file: the parse tree (for pointers) and the line starts.
  const parsed = useMemo(() => (text === null ? null : parseLua(text)), [text]);
  const starts = useMemo(() => (text === null ? [0] : lineStarts(text)), [text]);
  const lines = text === null ? 0 : starts.length;
  /** The block's lines (0-based, inclusive). */
  const focus = useMemo(() => {
    if (!parsed || !pointer) return null;
    const hit = locateIn(parsed, pointer);
    if (!hit) return null;
    return {
      partial: hit.partial,
      first: lineAt(starts, hit.start),
      last: lineAt(starts, Math.max(hit.start, hit.end - 1)),
    };
  }, [parsed, starts, pointer]);
  const [lineHeight, setLineHeight] = useState(0);
  const bytes = useMemo(() => (text === null ? 0 : new TextEncoder().encode(text).length), [text]);

  // Modal: lock the page, trap focus, Esc closes.
  useEffect(() => {
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    dialog.current?.focus();
    return () => {
      root.style.overflow = overflow;
    };
  }, []);

  // Bring the block into view (or the top for a whole file): arithmetic, no layout reads.
  useLayoutEffect(() => {
    const box = scroller.current;
    const code = codeRef.current;
    if (!box || !code || text === null) return;
    const lh = parseFloat(getComputedStyle(code).getPropertyValue("--lua-lh")) || 19;
    setLineHeight(lh);
    box.scrollTop = focus ? Math.max(0, CODE_PAD + focus.first * lh - 24) : 0;
  }, [text, focus]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    } else if (event.key === "Tab" && dialog.current) {
      const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null,
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialog.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };

  const fileBlocks = blocks.filter((b) => splitSourcePath(b.sourcePath).path === path);
  const fileName = `${fileStem(path)}.lua`;
  const labels = shortLabels(files);
  const downloadName =
    path === files[0] || !files.includes(path)
      ? `${safeName(recordId)}.lua`
      : `${safeName(recordId)}_${safeName(labels[files.indexOf(path)] ?? fileStem(path))}.lua`;

  const copy = async () => {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast(`Copied ${fileName}.`);
    } catch {
      showToast("Copy failed: the browser blocked the clipboard.");
    }
  };

  const download = () => {
    if (text === null) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/x-lua;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadName;
    document.body.append(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  let body: ReactNode;
  if (!current) {
    body = <p className="lua-status">Loading {fileName}…</p>;
  } else if ("error" in current) {
    body = <p className="lua-status lua-error">{current.error}</p>;
  } else if (text !== null) {
    body = (
      <section className="lua-scroll" ref={scroller} tabIndex={0} aria-label={`${fileName} source`}>
        <div className="lua-code" ref={codeRef}>
          <CodeBody text={text} tokens={tokens} lines={lines} />
          {focus && lineHeight ? (
            <div
              className="lua-focus"
              aria-hidden="true"
              style={{
                top: CODE_PAD + focus.first * lineHeight,
                height: (focus.last - focus.first + 1) * lineHeight,
              }}
            />
          ) : null}
        </div>
      </section>
    );
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop click closes the dialog
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled by the dialog
    <div
      className="lua-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="lua-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialog}
        onKeyDown={onKeyDown}
      >
        <header className="lua-head">
          <div className="lua-title">
            <p className="lua-kicker">Lua · {name}</p>
            <h2 id={titleId}>{fileName}</h2>
            <p className="lua-path">{path}</p>
          </div>
          <button type="button" className="icon-btn lua-close" aria-label="Close" onClick={onClose}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <p className="lua-note">
          DCS runtime table after scripts run, not the original source file; functions appear as
          markers.
        </p>

        {files.length > 1 ? (
          <fieldset className="lua-files seg">
            <legend className="visually-hidden">Source files</legend>
            {files.map((f, i) => (
              <button
                key={f}
                type="button"
                className="seg-btn"
                aria-pressed={f === path}
                title={f}
                onClick={() => onNavigate(f)}
              >
                {labels[i]}
              </button>
            ))}
          </fieldset>
        ) : null}

        <div className="lua-toolbar">
          {fileBlocks.length ? (
            <label className="lua-block">
              <span>Block</span>
              <select
                value={pointer ? sourcePath : ""}
                onChange={(event) => onNavigate(event.target.value || path)}
              >
                <option value="">Whole file</option>
                {fileBlocks.map((b) => (
                  <option key={`${b.label}:${b.sourcePath}`} value={b.sourcePath}>
                    {b.label} — {splitSourcePath(b.sourcePath).pointer}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <span className="lua-meta">
            {text !== null
              ? `${formatSize(bytes)} · ${lines.toLocaleString("en-US")} lines${tokens ? "" : " · plain text"}`
              : null}
          </span>
          <span className="lua-actions">
            <button
              type="button"
              className="btn btn-compact"
              disabled={text === null}
              onClick={copy}
            >
              Copy
            </button>
            <button
              type="button"
              className="btn btn-compact"
              disabled={text === null}
              onClick={download}
            >
              Download
            </button>
          </span>
        </div>

        {pointer && text !== null && (!focus || focus.partial) ? (
          <p className="lua-status lua-partial">
            {focus
              ? `${pointer} continues outside this file; its nearest table is marked.`
              : `${pointer} is not in this file.`}
          </p>
        ) : null}

        {body}
      </div>
    </div>
  );
}
