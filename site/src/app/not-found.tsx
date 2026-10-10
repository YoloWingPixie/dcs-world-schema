import type { Metadata } from "next";
import { ReferenceShell } from "@/components/reference-shell";

export const metadata: Metadata = { title: "DCS World Reference" };

/** Also 404.html, which the host serves for reference and API deep links (see _redirects). */
export default function NotFoundPage() {
  return (
    <div className="page">
      <ReferenceShell />
    </div>
  );
}
