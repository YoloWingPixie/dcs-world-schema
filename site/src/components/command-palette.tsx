"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

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
  const router = useRouter();
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
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled by the combobox
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop click closes the dialog
    <div
      className="palette-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search the reference">
        <GlobalSearch
          label="Search the reference"
          variant="palette"
          autoFocus
          onEscape={close}
          onPick={(item) => {
            setOpen(false);
            openHref(item.href, router);
          }}
          emptyHint={
            <div className="results-empty">
              Type a name (<code>F-16C</code>, <code>AMRAAM</code>), a DCS id (<code>P_27PE</code>),
              an airbase (<code>Batumi</code>) or a type (<code>radar</code>).{" "}
              <Link href="/reference/" onClick={() => setOpen(false)}>
                Browse every section
              </Link>
            </div>
          }
          footer={
            <div className="results-hint">
              <span>
                <span className="kbd">↑</span> <span className="kbd">↓</span> move
              </span>
              <span>
                <span className="kbd">Alt</span> <span className="kbd">←</span>{" "}
                <span className="kbd">→</span> section
              </span>
              <span>
                <span className="kbd">Enter</span> open
              </span>
              <span>
                <span className="kbd">Esc</span> close
              </span>
            </div>
          }
        />
      </div>
    </div>
  );
}
