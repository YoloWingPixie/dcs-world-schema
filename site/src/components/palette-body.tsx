"use client";

import { useRouter } from "next/navigation";
import { useRef } from "react";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";
import { useModalDialog } from "./use-modal-dialog";

/** The palette dialog; loaded on first open (see command-palette.tsx). */
export default function PaletteBody({
  close,
  dismiss,
}: {
  /** Close and return focus. */
  close: () => void;
  /** Close without restoring focus (navigation). */
  dismiss: () => void;
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDivElement>(null);
  // Escape is handled by the combobox; the page keeps its scrollbar.
  const onKeyDown = useModalDialog(dialog, close, { closeOnEscape: false, lockScroll: false });
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled by the combobox
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop click closes the dialog
    <div
      className="modal-backdrop palette-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={dialog}
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        onKeyDown={onKeyDown}
      >
        <GlobalSearch
          variant="palette"
          autoFocus
          onEscape={close}
          onPick={(item) => {
            dismiss();
            openHref(item.href, router);
          }}
          footer={
            <div className="results-hint">
              <span>
                <span className="kbd">↑</span> <span className="kbd">↓</span> move
              </span>
              <span>
                <span className="kbd">Alt</span> <span className="kbd">←</span>{" "}
                <span className="kbd">→</span> filter
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
