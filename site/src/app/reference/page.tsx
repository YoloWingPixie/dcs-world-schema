import type { Metadata } from "next";
import { SeriesDirectory } from "@/components/series-directory";

export const metadata: Metadata = {
  title: "Reference",
};

export default function ReferencePage() {
  return (
    <div className="page">
      <h1 className="page-title">Reference</h1>
      <SeriesDirectory />
    </div>
  );
}
