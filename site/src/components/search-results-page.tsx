"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

/** `/search/?q=`: every source's results on one page. */
export function SearchResultsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const initial = params.get("q") ?? "";
  const [query, setQuery] = useState(initial);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const q = query.trim();
      if (q === (params.get("q") ?? "")) return;
      router.replace(q ? `${pathname}?q=${encodeURIComponent(q)}` : pathname, { scroll: false });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, params, pathname, router]);
  return (
    <GlobalSearch
      label="Search the reference"
      variant="page"
      autoFocus
      initialQuery={initial}
      onQueryChange={setQuery}
      onPick={(item) => openHref(item.href, router)}
    />
  );
}
