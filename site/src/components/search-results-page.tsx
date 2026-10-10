"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { replaceQuery } from "@/lib/history";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

/** `/search/?q=`: every source's results on one page. */
export function SearchResultsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const initial = params.get("q") ?? "";
  const [query, setQuery] = useState(initial);
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
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const q = query.trim();
      if (q === (params.get("q") ?? "")) return;
      replaceQuery(q ? `q=${encodeURIComponent(q)}` : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, params]);
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
