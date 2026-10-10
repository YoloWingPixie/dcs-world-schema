import { type KeyboardEvent, type RefObject, useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Focus `el` after the current render settles (a closed dialog returning focus). */
export function focusLater(el: HTMLElement | null | undefined) {
  window.setTimeout(() => el?.focus(), 0);
}

/**
 * Modal behaviour for the dialog element `ref`: focus moves into it on mount (unless a
 * child already took it), Tab stays inside it, and Escape calls `onClose` (`closeOnEscape: false`
 * when a child handles Escape itself). `lockScroll` stops the page scrolling behind it.
 * Returns the dialog's onKeyDown.
 */
export function useModalDialog(
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
  {
    closeOnEscape = true,
    lockScroll = true,
  }: { closeOnEscape?: boolean; lockScroll?: boolean } = {},
) {
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const el = ref.current;
    if (el && !el.contains(document.activeElement)) el.focus();
    if (!lockScroll) return;
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = overflow;
    };
  }, [ref, lockScroll]);

  return (event: KeyboardEvent) => {
    const dialog = ref.current;
    if (event.key === "Escape" && closeOnEscape) {
      event.stopPropagation();
      close.current();
    } else if (event.key === "Tab" && dialog) {
      const items = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null,
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };
}
