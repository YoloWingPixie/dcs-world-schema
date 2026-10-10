"use client";

import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { loadCatalog, loadRecord } from "@/lib/client-data";
import { replaceQuery } from "@/lib/history";
import { luaAvailable, recordSources, splitSourcePath } from "@/lib/lua/source";
import { useLoaded } from "@/lib/use-loaded";
import { CodeIcon } from "@/ui/icons";
import { showToast } from "./toast";
import { focusLater } from "./use-modal-dialog";

// The drawer, its tokenizer and its styles load on first open.
const LuaDrawer = lazy(() => import("./lua-drawer"));

/** The query parameter holding the open dump path (`?lua=_G/a/b` or `_G/a/b#/x`). */
export const LUA_PARAM = "lua";
const OPEN_EVENT = "dcs-ref:open-lua";

/** Open the record's Lua drawer at a dump path or block `sourcePath` (for block links). */
export function openLua(sourcePath: string) {
  window.dispatchEvent(new CustomEvent<string>(OPEN_EVENT, { detail: sourcePath }));
}

function setParam(value: string | null) {
  const params = new URLSearchParams(window.location.search);
  params.delete(LUA_PARAM);
  // Slashes stay readable: ?lua=_G/db/Units/Planes/Plane/F-16C_50%23/SFM_Data/engine
  const query = [
    params.toString(),
    value === null ? "" : `${LUA_PARAM}=${encodeURIComponent(value).replace(/%2F/gi, "/")}`,
  ]
    .filter(Boolean)
    .join("&");
  replaceQuery(query);
}

// Whether this build has Lua files: one flag for the page, read by every "View Lua" link.
let luaKnown: boolean | null = null;
let luaAsked = false;
const luaListeners = new Set<() => void>();

function subscribeLua(listener: () => void) {
  luaListeners.add(listener);
  if (!luaAsked) {
    luaAsked = true;
    const settle = (v: boolean) => {
      luaKnown = v;
      for (const l of luaListeners) l();
    };
    luaAvailable().then(settle, () => settle(false));
  }
  return () => {
    luaListeners.delete(listener);
  };
}

/** Whether this build has Lua files (data/lua.json); false until known. */
export function useLuaAvailable(): boolean {
  return useSyncExternalStore(
    subscribeLua,
    () => luaKnown ?? false,
    () => false,
  );
}

/**
 * "View Lua" in the record plate: shown once the record is loaded and has sourcePaths, and
 * the build has Lua files (data/lua.json). Files that turn out missing drop out; with none
 * left the button hides.
 */
export function LuaButton({ series, slug }: { series: string; slug: string }) {
  const loaded = useLoaded(
    () => Promise.all([loadCatalog(series), loadRecord(series, slug)]),
    `${series}/${slug}`,
  );
  const doc = loaded?.[1];
  const [open, setOpen] = useState<string | null>(null);
  const available = useLuaAvailable();
  const [missing, setMissing] = useState<ReadonlySet<string>>(new Set());
  const button = useRef<HTMLButtonElement>(null);

  const sources = useMemo(() => {
    if (!loaded || !available) return { files: [], blocks: [] };
    const [catalog, record] = loaded;
    const all = recordSources(catalog, record.data, record.companion);
    return {
      files: all.files.filter((f) => !missing.has(f)),
      blocks: all.blocks.filter((b) => !missing.has(splitSourcePath(b.sourcePath).path)),
    };
  }, [loaded, available, missing]);

  /** A dump path the record has (its file, else its first), as the drawer opens it. */
  const pick = useCallback(
    (sourcePath: string | null) => {
      const first = sources.files[0];
      if (!first) return null;
      if (!sourcePath) return first;
      return sources.files.includes(splitSourcePath(sourcePath).path) ? sourcePath : first;
    },
    [sources],
  );

  // A linked ?lua= opens the drawer once the record is here.
  useEffect(() => {
    if (!sources.files.length) return;
    const linked = new URLSearchParams(window.location.search).get(LUA_PARAM);
    if (linked !== null) setOpen(pick(linked));
  }, [sources, pick]);

  useEffect(() => {
    const onOpen = (event: Event) => {
      const target = pick((event as CustomEvent<string>).detail);
      if (!target) return;
      setOpen(target);
      setParam(target);
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, [pick]);

  const show = (target: string | null) => {
    setOpen(target);
    setParam(target);
  };

  if (!doc || !sources.files.length) return null;
  return (
    <>
      <button
        ref={button}
        type="button"
        className="btn"
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        onClick={() => show(pick(null))}
      >
        <CodeIcon />
        View Lua
      </button>
      {open !== null ? (
        <Suspense fallback={null}>
          <LuaDrawer
            recordId={doc.id}
            name={doc.name}
            files={sources.files}
            blocks={sources.blocks}
            sourcePath={open}
            onNavigate={show}
            onMissing={(path) => {
              const left = sources.files.filter((f) => f !== path);
              setMissing((m) => new Set([...m, path]));
              if (left[0]) {
                show(left[0]);
              } else {
                show(null);
                showToast(`This build has no Lua for ${doc.name}.`);
              }
            }}
            onClose={() => {
              show(null);
              focusLater(button.current);
            }}
          />
        </Suspense>
      ) : null}
    </>
  );
}
