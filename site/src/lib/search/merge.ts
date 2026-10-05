import type { SourceHits } from "./types";

/** Groups ordered by their best hit; empty groups dropped. */
export function mergeHits(groups: SourceHits[]): SourceHits[] {
  return groups
    .filter((g) => g.results.length > 0)
    .sort(
      (a, b) =>
        (b.results[0]?.score ?? 0) - (a.results[0]?.score ?? 0) ||
        (a.source.priority ?? 100) - (b.source.priority ?? 100),
    );
}
