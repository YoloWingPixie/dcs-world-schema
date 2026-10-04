"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { addRecords, compareHref, getCompare, removeRecord, setCompare } from "@/lib/compare-store";
import { SERIES_BY_ID } from "@/lib/series";
import { CompareIcon, CopyIcon, PlusIcon } from "@/ui/icons";
import { showToast } from "./toast";

type Target = {
  el: HTMLElement;
  path: string;
  label: string;
  comparable: boolean;
  text: string;
  stored: string | null;
  series: string;
  record: string | null;
  recordName: string | null;
  x: number;
  y: number;
};

function readTarget(el: HTMLElement, x: number, y: number): Target {
  return {
    el,
    path: el.dataset.field ?? "",
    label: el.dataset.fieldLabel ?? el.dataset.field ?? "",
    comparable: el.dataset.fieldComparable !== "false",
    text: el.dataset.fieldText ?? "",
    stored: el.dataset.fieldStored ?? null,
    series: el.dataset.series ?? "weapons",
    record: el.dataset.record ?? null,
    recordName: el.dataset.recordName ?? null,
    x,
    y,
  };
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`Copied ${what}.`);
  } catch {
    showToast("Copying is blocked in this browser.");
  }
}

/** Starts a field comparison; shared by the menu, the C shortcut and the compare page. */
export function compareFieldHref(series: string, path: string, record: string | null): string {
  const state = getCompare(series);
  const records = record ? [record, ...state.records.filter((r) => r !== record)] : state.records;
  const next = { series, field: path, records };
  setCompare(next);
  return compareHref(next);
}

/**
 * One delegated context menu for every element carrying data-field: right-click,
 * the ⋯ button, Shift+F10 / the menu key, long-press on touch, and C to compare.
 */
export function FieldMenu() {
  const router = useRouter();
  const [target, setTarget] = useState<Target | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = useCallback((restoreFocus: boolean) => {
    setTarget((t) => {
      if (t) {
        t.el.removeAttribute("data-menu-open");
        if (restoreFocus) t.el.focus();
      }
      return null;
    });
  }, []);

  const openAt = useCallback((el: HTMLElement, x: number, y: number) => {
    setTarget((prev) => {
      prev?.el.removeAttribute("data-menu-open");
      return readTarget(el, x, y);
    });
    el.setAttribute("data-menu-open", "true");
  }, []);

  useEffect(() => {
    let pressTimer: number | null = null;
    let pressStart: { x: number; y: number } | null = null;

    const fieldOf = (node: EventTarget | null) =>
      (node as HTMLElement | null)?.closest<HTMLElement>("[data-field]") ?? null;

    const onContextMenu = (event: MouseEvent) => {
      const el = fieldOf(event.target);
      if (!el) return;
      event.preventDefault();
      if (event.clientX === 0 && event.clientY === 0) {
        const rect = el.getBoundingClientRect();
        openAt(el, rect.left + 24, rect.bottom);
      } else {
        openAt(el, event.clientX, event.clientY);
      }
    };

    const onClick = (event: MouseEvent) => {
      const button = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        "[data-field-menu-button]",
      );
      const el = button ? fieldOf(button) : null;
      if (!button || !el) return;
      event.preventDefault();
      const rect = button.getBoundingClientRect();
      openAt(el, rect.right - 260, rect.bottom + 4);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      const el = event.target as HTMLElement | null;
      if (!el?.matches?.("[data-field]")) return;
      if (event.key === "Enter" || (event.shiftKey && event.key === "F10")) {
        event.preventDefault();
        const rect = el.getBoundingClientRect();
        openAt(el, rect.left + 24, rect.bottom);
      } else if (
        event.key.toLowerCase() === "c" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        const t = readTarget(el, 0, 0);
        if (!t.comparable) return;
        event.preventDefault();
        router.push(compareFieldHref(t.series, t.path, t.record));
      }
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      const el = fieldOf(event.target);
      if (!el) return;
      pressStart = { x: event.clientX, y: event.clientY };
      pressTimer = window.setTimeout(() => {
        if (pressStart) openAt(el, pressStart.x, pressStart.y);
        pressTimer = null;
      }, 520);
    };
    const cancelPress = (event: PointerEvent) => {
      if (pressTimer === null) return;
      if (event.type === "pointermove" && pressStart) {
        if (Math.hypot(event.clientX - pressStart.x, event.clientY - pressStart.y) < 10) return;
      }
      window.clearTimeout(pressTimer);
      pressTimer = null;
    };

    document.addEventListener("contextmenu", onContextMenu);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("pointermove", cancelPress);
    document.addEventListener("pointerup", cancelPress);
    document.addEventListener("pointercancel", cancelPress);
    return () => {
      document.removeEventListener("contextmenu", onContextMenu);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("pointermove", cancelPress);
      document.removeEventListener("pointerup", cancelPress);
      document.removeEventListener("pointercancel", cancelPress);
    };
  }, [openAt, router]);

  // Place inside the viewport, then focus the first item.
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!target || !menu) {
      setPos(null);
      return;
    }
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(target.x, window.innerWidth - rect.width - 8));
    const top =
      target.y + rect.height + 8 > window.innerHeight
        ? Math.max(8, target.y - rect.height)
        : target.y;
    setPos({ left, top });
    menu.querySelector<HTMLElement>("[role='menuitem']")?.focus();
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const onDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) close(false);
    };
    const onScroll = () => close(false);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("resize", onScroll);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("scroll", onScroll);
    };
  }, [target, close]);

  if (!target) return null;

  const inCompare = target.record
    ? getCompare(target.series).records.includes(target.record)
    : false;
  const plural = SERIES_BY_ID.get(target.series)?.label.toLowerCase() ?? "records";

  const run = (action: () => void) => () => {
    close(false);
    action();
  };

  const items: Array<
    { key: string; label: string; icon: React.ReactNode; hint?: string; act: () => void } | "sep"
  > = [];
  if (target.comparable) {
    items.push({
      key: "compare",
      label: `Compare ${target.label} across ${plural}`,
      icon: <CompareIcon />,
      hint: "C",
      act: () => router.push(compareFieldHref(target.series, target.path, target.record)),
    });
  }
  if (target.record && target.recordName) {
    const record = target.record;
    const name = target.recordName;
    const series = target.series;
    items.push(
      inCompare
        ? {
            key: "remove",
            label: `Remove ${name} from compare`,
            icon: <PlusIcon style={{ transform: "rotate(45deg)" }} />,
            act: () => {
              removeRecord(series, record);
              showToast(`Removed ${name} from compare.`);
            },
          }
        : {
            key: "add",
            label: `Add ${name} to compare`,
            icon: <PlusIcon />,
            act: () => {
              addRecords(series, record);
              const state = getCompare(series);
              showToast(
                `Added ${name} to compare (${state.records.length}).`,
                compareHref({ ...state, field: null }),
                "Open compare",
              );
            },
          },
    );
  }
  items.push("sep");
  items.push({
    key: "copy",
    label: target.stored ? `Copy value (${target.text})` : "Copy value",
    icon: <CopyIcon />,
    act: () => copy(target.text, "value"),
  });
  if (target.stored) {
    const stored = target.stored;
    items.push({
      key: "copy-stored",
      label: `Copy stored value (${stored})`,
      icon: <CopyIcon />,
      act: () => copy(stored, "stored value"),
    });
  }
  items.push({
    key: "path",
    label: "Copy field path",
    icon: <CopyIcon />,
    act: () => copy(target.path, "field path"),
  });

  const onMenuKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const nodes = [...(menuRef.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? [])];
    const i = nodes.indexOf(document.activeElement as HTMLElement);
    const focus = (n: number) => nodes[(n + nodes.length) % nodes.length]?.focus();
    if (event.key === "ArrowDown") focus(i + 1);
    else if (event.key === "ArrowUp") focus(i - 1);
    else if (event.key === "Home") focus(0);
    else if (event.key === "End") focus(nodes.length - 1);
    else if (event.key === "Escape") close(true);
    else if (event.key === "Tab") close(true);
    else if (event.key.toLowerCase() === "c" && target.comparable) {
      close(false);
      router.push(compareFieldHref(target.series, target.path, target.record));
    } else return;
    event.preventDefault();
  };

  return (
    <div
      ref={menuRef}
      className="menu"
      role="menu"
      aria-label={`${target.label} actions`}
      style={pos ? { left: pos.left, top: pos.top } : { left: -9999, top: 0 }}
      onKeyDown={onMenuKey}
    >
      <div className="menu-head" aria-hidden="true">
        <span className="menu-head-label">{target.label}</span>
        <span className="menu-head-path">{target.path}</span>
        {target.stored ? <span className="menu-head-path">Stored as {target.stored}</span> : null}
      </div>
      {items.map((item, i) =>
        item === "sep" ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: separators are positional
          <hr className="menu-sep" key={`sep${i}`} />
        ) : (
          <button
            key={item.key}
            type="button"
            role="menuitem"
            className="menu-item"
            tabIndex={-1}
            onClick={run(item.act)}
          >
            {item.icon}
            <span>{item.label}</span>
            {item.hint ? <span className="kbd">{item.hint}</span> : null}
          </button>
        ),
      )}
    </div>
  );
}
