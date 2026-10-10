"use client";

import Link from "next/link";
import { compareHref, toggleInCompare, useCompareRecords } from "@/lib/compare-store";
import { CompareIcon, PlusIcon } from "@/ui/icons";
import { LuaButton } from "./lua-button";

export function RecordCompareActions({
  series,
  slug,
  name,
}: {
  series: string;
  slug: string;
  name: string;
}) {
  const records = useCompareRecords(series);
  const inCompare = records.includes(slug);
  const others = records.filter((r) => r !== slug);
  return (
    <div className="plate-actions">
      <button
        type="button"
        className={inCompare ? "btn" : "btn btn-primary"}
        aria-pressed={inCompare}
        onClick={() => toggleInCompare(series, slug, name)}
      >
        <PlusIcon style={inCompare ? { transform: "rotate(45deg)" } : undefined} />
        {inCompare ? "In compare" : "Add to compare"}
      </button>
      <Link className="btn" href={compareHref({ series, field: null, records: [slug, ...others] })}>
        <CompareIcon />
        {others.length ? `Compare (${others.length + 1})` : "Compare"}
      </Link>
      <LuaButton series={series} slug={slug} />
    </div>
  );
}
