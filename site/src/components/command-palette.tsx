"use client";

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

// The dialog and the search engine behind it load on first open.
const PaletteBody = lazy(() => import("./palette-body"));

const OPEN_EVENT = "dcs-ref:open-palette";

export function openPalette() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return Boolean(el?.closest("input, textarea, select, [contenteditable='true']"));
}

/** Global command palette: Ctrl/Cmd+K or "/" anywhere. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);

  const show = useCallback(() => {
    returnFocus.current = document.activeElement as HTMLElement | null;
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    window.setTimeout(() => returnFocus.current?.focus(), 0);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const k = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && k === "k") {
        event.preventDefault();
        setOpen((o) => {
          if (!o) returnFocus.current = document.activeElement as HTMLElement | null;
          return !o;
        });
      } else if (event.key === "/" && !isTyping(event.target) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        show();
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, show);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, show);
    };
  }, [show]);

  if (!open) return null;
  return (
    <Suspense
      fallback={
        <div className="palette-backdrop">
          <div className="palette" role="dialog" aria-label="Search" aria-busy="true">
            <span className="visually-hidden">Loading…</span>
          </div>
        </div>
      }
    >
      <PaletteBody close={close} dismiss={() => setOpen(false)} />
    </Suspense>
  );
}
