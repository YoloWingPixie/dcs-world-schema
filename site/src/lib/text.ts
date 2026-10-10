/** `fixedwing` -> `Fixedwing`. */
export const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Lowercase with only letters and digits kept: "AIM-120C" and "aim 120c" both give "aim120c". */
export const squash = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/** Natural, case-aware ordering ("F-14" before "F-100"); one shared collator. */
export const naturalCompare = new Intl.Collator("en", { numeric: true }).compare;

/** `naturalCompare` that also ignores case and accents ("abc" and "ABC" tie). */
export const naturalCompareBase = new Intl.Collator("en", { numeric: true, sensitivity: "base" })
  .compare;

/**
 * Two sort keys in direction `dir` (1 ascending, -1 descending): numbers by value, anything
 * else as text in natural order. Missing keys (null, undefined, "") sort last either way.
 */
export function compareSortKeys(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
  dir: 1 | -1,
): number {
  const aMissing = a === null || a === undefined || a === "";
  const bMissing = b === null || b === undefined || b === "";
  if (aMissing || bMissing) return aMissing === bMissing ? 0 : aMissing ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return dir * (a - b);
  return dir * naturalCompare(String(a), String(b));
}
