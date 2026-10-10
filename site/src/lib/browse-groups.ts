/**
 * Grouped browse lists (components/browse-view.tsx): rows under a heading per group,
 * laid out for the virtualised table as one list of fixed-height items.
 */

/** Where a row belongs: `key` identifies the group, `label` names it. */
export type GroupOf = {
  key: string;
  label: string;
  /** Site path of the record the heading links to. */
  href?: string;
  /** A short secondary label (the folder or id behind the name). */
  sub?: string;
};

export type Group<R> = GroupOf & { rows: R[] };

export type Item<R> =
  | { kind: "group"; group: Group<R>; number: number }
  | { kind: "row"; row: R; group?: Group<R> };

const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

/**
 * Rows (already in display order) into groups sorted by label; rows keep their order
 * inside a group. `last` keys sort after every other group. Only groups with rows exist.
 */
export function groupRows<R>(
  rows: readonly R[],
  groupOf: (row: R) => GroupOf,
  last?: (key: string) => boolean,
): Group<R>[] {
  const byKey = new Map<string, Group<R>>();
  for (const row of rows) {
    const g = groupOf(row);
    let group = byKey.get(g.key);
    if (!group) {
      group = { ...g, rows: [] };
      byKey.set(g.key, group);
    }
    group.rows.push(row);
  }
  const rank = (g: Group<R>) => (last?.(g.key) ? 1 : 0);
  return [...byKey.values()].sort(
    (a, b) =>
      rank(a) - rank(b) || collator.compare(a.label, b.label) || collator.compare(a.key, b.key),
  );
}

export type Layout<R> = {
  items: Item<R>[];
  /** Top of each item; `tops[items.length]` is the total height. */
  tops: number[];
};

/** Groups (or flat rows) as one item list with cumulative tops. */
export function layoutItems<R>(
  source: { groups: Group<R>[] } | { rows: readonly R[] },
  rowH: number,
  groupH: number,
): Layout<R> {
  const items: Item<R>[] = [];
  const tops: number[] = [0];
  let y = 0;
  const push = (item: Item<R>, h: number) => {
    items.push(item);
    y += h;
    tops.push(y);
  };
  if ("groups" in source) {
    source.groups.forEach((group, i) => {
      push({ kind: "group", group, number: i + 1 }, groupH);
      for (const row of group.rows) push({ kind: "row", row, group }, rowH);
    });
  } else {
    for (const row of source.rows) push({ kind: "row", row }, rowH);
  }
  return { items, tops };
}

/** First item whose bottom is below `y` (binary search over `tops`). */
function itemAt(tops: readonly number[], y: number): number {
  let lo = 0;
  let hi = tops.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((tops[mid + 1] ?? Number.POSITIVE_INFINITY) <= y) lo = mid + 1;
    else hi = mid;
  }
  return Math.min(lo, tops.length - 2);
}

/** `[start, end)` of the items to render for a viewport, with `overscan` items each side. */
export function visibleRange(
  tops: readonly number[],
  scrollTop: number,
  viewH: number,
  overscan: number,
): [number, number] {
  const count = tops.length - 1;
  if (count <= 0) return [0, 0];
  const first = itemAt(tops, Math.max(0, scrollTop));
  const last = itemAt(tops, scrollTop + viewH);
  return [Math.max(0, first - overscan), Math.min(count, last + 1 + overscan)];
}

/**
 * A column's width from the text lengths of all its cells: the 90th percentile (a few
 * long outliers ellipsise rather than widen the column), never narrower than its head;
 * in `ch`, capped at 30.
 */
export function columnWidth(lengths: number[], header: number): number {
  const sorted = lengths.filter((n) => n > 0).sort((a, b) => a - b);
  const p90 = sorted.length ? (sorted[Math.floor((sorted.length - 1) * 0.9)] ?? 0) : 0;
  return Math.min(30, Math.max(6, header + 2, p90 + 1));
}
