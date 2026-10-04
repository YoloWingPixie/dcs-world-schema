"use client";

import { useRouter } from "next/navigation";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

export function HomeSearch() {
  const router = useRouter();
  return (
    <div className="home-search">
      <GlobalSearch
        label="Search the reference"
        variant="inline"
        placeholder="Try “F-16C”, “amraam”, “Batumi”, “APG-68”, “P_27PE”…"
        onPick={(item) => openHref(item.href, router)}
        footer={
          <div className="results-hint">
            <span>
              <span className="kbd">Enter</span> open the highlighted record
            </span>
            <span>
              <span className="kbd">Alt</span> <span className="kbd">←</span>{" "}
              <span className="kbd">→</span> filter by section
            </span>
            <span>Typos are fine.</span>
          </div>
        }
      />
    </div>
  );
}
