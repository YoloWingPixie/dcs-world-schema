import type { Metadata } from "next";
import { Suspense } from "react";
import { CompareView } from "@/components/compare-view";

export const metadata: Metadata = { title: "Compare" };

export default function ComparePage() {
  return (
    <div className="page">
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <CompareView />
      </Suspense>
    </div>
  );
}
