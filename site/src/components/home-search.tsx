"use client";

import { useRouter } from "next/navigation";
import { GlobalSearch } from "./global-search";
import { openHref } from "./ref-link";

export function HomeSearch() {
  const router = useRouter();
  return (
    <div className="home-search">
      <GlobalSearch
        label="Search"
        variant="inline"
        onPick={(item) => openHref(item.href, router)}
      />
    </div>
  );
}
