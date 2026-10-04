import type { Metadata } from "next";
import { Suspense } from "react";
import { SearchResultsPage } from "@/components/search-results-page";

export const metadata: Metadata = { title: "Search" };

export default function SearchPage() {
  return (
    <div className="page">
      <h1 className="page-title">Search</h1>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <SearchResultsPage />
      </Suspense>
    </div>
  );
}
