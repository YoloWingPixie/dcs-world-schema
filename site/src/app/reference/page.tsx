import type { Metadata } from "next";
import { SeriesDirectory } from "@/components/series-directory";

export const metadata: Metadata = {
  title: "Reference",
  description: "Every series of DCS World reference data, with record counts.",
};

export default function ReferencePage() {
  return (
    <div className="page">
      <h1 className="page-title">Reference</h1>
      <p className="lede">
        Every series the extractor reads from DCS World. Open one to browse, filter and sort its
        records; every record links to the records it names and the ones that name it.
      </p>
      <SeriesDirectory />
    </div>
  );
}
