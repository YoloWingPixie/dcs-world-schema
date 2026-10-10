"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryParam } from "@/lib/use-query-param";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

/** `/search/?q=`: every source's results on one page. */
export function SearchResultsPage() {
  const router = useRouter();
  const [query, setQuery, initial] = useQueryParam("q", 300);
  // A `?q=` this page did not write (a link, back/forward) restarts the search box with it.
  const [seen, setSeen] = useState(initial);
  const [generation, setGeneration] = useState(0);
  if (initial !== seen) {
    setSeen(initial);
    if (initial !== query.trim()) {
      setQuery(initial);
      setGeneration((g) => g + 1);
    }
  }
  return (
    <GlobalSearch
      key={generation}
      variant="page"
      autoFocus
      initialQuery={initial}
      onQueryChange={setQuery}
      onPick={(item) => openHref(item.href, router)}
    />
  );
}
