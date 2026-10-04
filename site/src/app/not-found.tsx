import type { Metadata } from "next";
import { ReferenceShell } from "@/components/reference-shell";

export const metadata: Metadata = { title: "DCS World Reference" };

/** Also the GitHub Pages 404.html: the client-side home of every reference page. */
export default function NotFoundPage() {
  return (
    <div className="page">
      <ReferenceShell />
    </div>
  );
}
