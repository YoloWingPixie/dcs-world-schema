/** Which column a table is sorted by, and which way (1 ascending, -1 descending). */
export type SortState<K extends string = string> = { key: K; dir: 1 | -1 };

/**
 * A sortable column head: a button that sorts by `sortKey`, or flips the direction when
 * the table is already sorted by it. Numeric columns (`num`) sort largest first.
 */
export function SortHeader<K extends string>({
  sortKey,
  label,
  sort,
  onSort,
  num = false,
  className,
  title,
}: {
  sortKey: K;
  label: string;
  sort: SortState<K>;
  onSort: (next: SortState<K>) => void;
  num?: boolean;
  className?: string | undefined;
  title?: string | undefined;
}) {
  const active = sort.key === sortKey;
  return (
    <th
      scope="col"
      className={[num ? "num" : "", className ?? ""].filter(Boolean).join(" ") || undefined}
      aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      title={title}
    >
      <button
        type="button"
        className="sort-btn"
        data-active={active}
        onClick={() =>
          onSort({ key: sortKey, dir: active ? (sort.dir === 1 ? -1 : 1) : num ? -1 : 1 })
        }
      >
        {label}
        <span aria-hidden="true">{active ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}
